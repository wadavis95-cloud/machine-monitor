import argparse
import json
import re
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from textwrap import indent
from threading import Thread
from time import perf_counter

from httpx import ConnectError
from langchain_core.messages import ToolMessage
from ollama import ResponseError
from werkzeug.serving import make_server

from assistant.eam import load_predictions
from assistant.graph import build_graph, make_tools, run_question
from assistant.hexagon_eam import HexagonEAM
from assistant.routes import MODEL_ERROR, chat_model_factory
from assistant.scoring import chain_ok, drafts_ok, facts_ok, invented_ids, tools_ok
from assistant.seed import DATA_DIR, build_eam
from assistant.tools import fleet_status, load_context
from evals.assistant_golden import MISSING_RUL_CASE, golden_items
from loader import load_data
from mock_hexagon.app import create_app as create_mock_app

REPORT = DATA_DIR.parent / "reports" / "assistant_eval.md"
COLUMNS = ("Tools", "Facts", "IDs", "Drafts", "Sources", "PM label", "Chain", "Overall")
ANSWER_PREVIEW_LIMIT = 600
NEXT_PM_VALUE = re.compile(
    r"\bnext\s+pm\b(?:[\s:=|(]|\b(?:date|cycle|is|at|on)\b)*\d",
    re.IGNORECASE,
)


def sources_ok(answer, called, tool_names):
    # A tool mentioned in prose is a citation only when marked as a tag.
    answer = answer.casefold()
    cited = set(re.findall(r"\[([a-z_]+)\]", answer))
    for line in answer.splitlines():
        sources = re.match(
            r"\s*(?:[-*+]\s+)?(?:\*\*)?sources?\s*(?:\*\*)?\s*:\s*(.*)",
            line,
        )
        if sources:
            cited.update(re.findall(r"\b[a-z_]+\b", sources[1]))
    return (cited & tool_names).issubset(called)


def _prepare_case(item, ctx):
    if item["id"] == MISSING_RUL_CASE:
        # The normal seed has estimates for every unit. Hide one in this case only.
        (engine,) = fleet_status(ctx, top_n=1)
        ctx.predictions.pop((engine["unit"], engine["current_cycle"]), None)


def score_item(item, ctx, model, *, facts=None):
    _prepare_case(item, ctx)
    if facts is None:
        facts = item["expected_facts"](ctx)
    tools = make_tools(ctx)
    tool_results = []

    def collect_results(run):
        # The UI's step previews are truncated. The graph keeps full tool messages.
        for message in run.outputs["messages"]:
            if not isinstance(message, ToolMessage):
                continue
            if message.status == "success":
                tool_results.append(message.content)
            elif message.name == "draft_work_order" and message.content.startswith("{"):
                # A blocked draft can still return real open work order IDs.
                for order in json.loads(message.content).get("open_work_orders", []):
                    tool_results.append(order["wo_id"])

    graph = build_graph(model.bind_tools(tools), tools, ctx=ctx)
    result = run_question(
        graph.with_listeners(on_end=collect_results), item["question"]
    )

    answer = result["answer"]
    called = [call["name"] for call in result["tool_calls"]]
    plain_answer = answer.replace("*", "").replace("`", "")
    call_args = [json.dumps(call["args"]) for call in result["tool_calls"]]
    references = "\n".join([item["question"], *call_args])
    missing_ids = invented_ids(answer, "\n".join(tool_results), references)
    forbidden_calls = sorted(set(called) & item.get("forbid_tools", set()))
    forbidden_facts = [
        fact
        for fact in item.get("forbidden_facts", [])
        if facts_ok(plain_answer, [fact])
    ]
    pattern = item.get("expected_pattern")
    matches_pattern = pattern is None or bool(
        re.search(pattern, plain_answer, re.IGNORECASE)
    )
    checks = [
        tools_ok(called, item["expect_tools"]) and not forbidden_calls,
        facts_ok(answer, facts) and matches_pattern and not forbidden_facts,
        not missing_ids,
        drafts_ok(result["drafts"], item["should_draft"]),
        sources_ok(answer, called, {tool.name for tool in tools}),
        not NEXT_PM_VALUE.search(plain_answer),
        chain_ok(result["tool_calls"], item.get("expect_units")),
    ]
    overall = all(checks)
    failure = []
    if not overall:
        missing_facts = [fact for fact in facts if not facts_ok(answer, [fact])]
        preview = answer[:ANSWER_PREVIEW_LIMIT]
        if len(answer) > ANSWER_PREVIEW_LIMIT:
            preview += "…"
        forbidden_details = []
        if forbidden_calls:
            forbidden_details.append(
                f"- **Unexpected tools** {', '.join(forbidden_calls)}"
            )
        if not matches_pattern:
            forbidden_details.append(f"- **Missing answer pattern** `{pattern}`")
        if forbidden_facts:
            forbidden_details.append(
                f"- **Forbidden facts** {', '.join(forbidden_facts)}"
            )
        failure = [
            "",
            f"#### {item['id']}",
            "",
            f"- **Question** {item['question']}",
            f"- **Expected facts** {', '.join(facts) or 'None'}",
            f"- **Missing facts** {', '.join(missing_facts) or 'None'}",
            f"- **Invented IDs** {', '.join(missing_ids) or 'None'}",
            f"- **Tools called** {', '.join(called) or 'None'}",
            *forbidden_details,
            "",
            "**Final answer**",
            "",
            indent(preview if preview.strip() else "(empty answer)", "    "),
        ]
    return [*checks, overall], failure


@contextmanager
def serve_mock():
    api_key = token_urlsafe(24)
    app = create_mock_app(api_key=api_key, mode="normal", ignore_idempotency=False)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    worker = Thread(target=server.serve_forever)
    try:
        worker.start()
        try:
            yield HexagonEAM(f"http://127.0.0.1:{server.server_port}", api_key)
        finally:
            server.shutdown()
            worker.join()
    finally:
        server.server_close()


def _run_adapter(name, db_path, items, expected, model, *, eam=None):
    adapter_started = perf_counter()
    lines = [
        "",
        f"## {name}",
        "",
        "| Item | " + " | ".join(COLUMNS) + " | Duration (s) |",
        "| " + " | ".join(["---"] * (len(COLUMNS) + 2)) + " |",
    ]
    print("\n".join(lines), flush=True)
    scores = []
    failures = []
    for item in items:
        case_started = perf_counter()
        with TemporaryDirectory() as folder:
            ctx = load_context(
                db_path, DATA_DIR, eam=eam, draft_path=Path(folder) / "assistant.sqlite"
            )
            checks, failure = score_item(item, ctx, model, facts=expected[item["id"]])
        elapsed = perf_counter() - case_started
        scores.append(checks)
        failures.extend(failure)
        cells = ["pass" if check else "fail" for check in checks]
        row = "| " + " | ".join([item["id"], *cells, f"{elapsed:.2f}"]) + " |"
        lines.append(row)
        print(row, flush=True)

    totals = [f"{sum(column)}/{len(items)}" for column in zip(*scores, strict=True)]
    duration = perf_counter() - adapter_started
    summary = "| Total | " + " | ".join([*totals, f"{duration:.2f}"]) + " |"
    lines.append(summary)
    print(summary, flush=True)
    if failures:
        lines.extend(["", "### Failures", *failures])
    return lines


def main(argv=()):
    parser = argparse.ArgumentParser(
        description="Score maintenance assistant golden cases."
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="ID",
        help="Case IDs, separated by spaces or commas.",
    )
    parser.add_argument(
        "--adapter",
        choices=("sqlite", "hexagon"),
        help="Run one adapter. The default runs both.",
    )
    args = parser.parse_args(argv)
    selected = (
        {case.strip() for group in args.only for case in group.split(",")}
        if args.only is not None
        else set()
    )
    if "" in selected:
        parser.error("--only requires nonempty case IDs")

    readings = load_data(DATA_DIR / "train_FD001.txt")
    predictions = load_predictions(DATA_DIR / "predictions_FD001.csv")

    with TemporaryDirectory() as folder:
        db_path = Path(folder) / "eam.sqlite"
        build_eam(db_path, readings, predictions, seed=0)
        baseline = load_context(db_path, DATA_DIR)
        items = golden_items(baseline)
        if selected:
            unknown = selected - {item["id"] for item in items}
            if unknown:
                parser.error(f"unknown case IDs: {', '.join(sorted(unknown))}")
            items = [item for item in items if item["id"] in selected]
        model = chat_model_factory()
        lines = [
            "# Maintenance assistant eval",
            "",
            f"Model `{model.model}` · {date.today().isoformat()}",
        ]
        print("\n".join(lines), flush=True)
        expected = {}
        for item in items:
            ctx = replace(baseline, predictions=baseline.predictions.copy())
            _prepare_case(item, ctx)
            expected[item["id"]] = item["expected_facts"](ctx)
        if args.adapter in (None, "sqlite"):
            lines.extend(_run_adapter("SQLite", db_path, items, expected, model))
        if args.adapter in (None, "hexagon"):
            with serve_mock() as eam:
                lines.extend(
                    _run_adapter("Hexagon", db_path, items, expected, model, eam=eam)
                )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (ConnectError, ConnectionError) as error:
        raise SystemExit(MODEL_ERROR) from error
    except ResponseError as error:
        if error.status_code != 404:
            raise
        raise SystemExit(MODEL_ERROR) from error
