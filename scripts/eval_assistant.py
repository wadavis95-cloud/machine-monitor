import re
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from httpx import ConnectError
from langchain_core.messages import ToolMessage
from ollama import ResponseError

from assistant.eam import load_predictions
from assistant.graph import build_graph, make_tools, run_question
from assistant.routes import MODEL_ERROR, chat_model_factory
from assistant.scoring import drafts_ok, facts_ok, invented_ids, tools_ok
from assistant.seed import DATA_DIR, build_eam
from assistant.tools import fleet_status, load_context
from evals.assistant_golden import MISSING_RUL_CASE, golden_items
from loader import load_data

REPORT = DATA_DIR.parent / "reports" / "assistant_eval.md"
COLUMNS = ("Tools", "Facts", "IDs", "Drafts", "Sources", "PM label", "Overall")
NEXT_PM_VALUE = re.compile(
    r"\bnext\s+pm\b(?:[\s:=|(]|\b(?:date|cycle|is|at|on)\b)*\d",
    re.IGNORECASE,
)


def sources_ok(answer, called, tool_names):
    # Accept tool tags in the answer and bare tool names on a Sources line.
    marked = re.findall(r"\[([a-z_]+)\]|`([a-z_]+)`", answer.casefold())
    cited = {bracketed or quoted for bracketed, quoted in marked}
    for line in answer.casefold().splitlines():
        if re.search(r"\bsources?\s*\**\s*:", line):
            cited.update(re.findall(r"\b[a-z_]+\b", line))
    return (cited & tool_names).issubset(called)


def score_item(item, ctx, model):
    if item["id"] == MISSING_RUL_CASE:
        # The normal seed has estimates for every unit. Hide one in this case only.
        (engine,) = fleet_status(ctx, top_n=1)
        ctx.predictions.pop((engine["unit"], engine["current_cycle"]), None)
    facts = item["expected_facts"](ctx)
    tools = make_tools(ctx)
    tool_results = []

    def collect_results(run):
        # The UI's step previews are truncated. The graph keeps full tool messages.
        tool_results.extend(
            message.content
            for message in run.outputs["messages"]
            if isinstance(message, ToolMessage) and message.status == "success"
        )

    graph = build_graph(model.bind_tools(tools), tools, ctx=ctx)
    result = run_question(
        graph.with_listeners(on_end=collect_results), item["question"]
    )

    answer = result["answer"]
    called = [call["name"] for call in result["tool_calls"]]
    plain_answer = answer.replace("*", "").replace("`", "")
    checks = [
        tools_ok(called, item["expect_tools"]),
        facts_ok(answer, facts),
        not invented_ids(answer, "\n".join(tool_results)),
        drafts_ok(result["drafts"], item["should_draft"]),
        sources_ok(answer, called, {tool.name for tool in tools}),
        not NEXT_PM_VALUE.search(plain_answer),
    ]
    return [*checks, all(checks)]


def main():
    readings = load_data(DATA_DIR / "train_FD001.txt")
    predictions = load_predictions(DATA_DIR / "predictions_FD001.csv")
    model = chat_model_factory()

    def fresh_context(folder):
        db_path = Path(folder) / "eam.sqlite"
        build_eam(db_path, readings, predictions, seed=0)
        return load_context(db_path, DATA_DIR)

    with TemporaryDirectory() as folder:
        items = golden_items(fresh_context(folder))

    lines = [
        "# Maintenance assistant eval",
        "",
        f"Model `{model.model}` · {date.today().isoformat()}",
        "",
        "| Item | " + " | ".join(COLUMNS) + " |",
        "| " + " | ".join(["---"] * (len(COLUMNS) + 1)) + " |",
    ]
    print("\n".join(lines), flush=True)
    scores = []
    for item in items:
        with TemporaryDirectory() as folder:
            checks = score_item(item, fresh_context(folder), model)
        scores.append(checks)
        cells = ["pass" if check else "fail" for check in checks]
        row = "| " + " | ".join([item["id"], *cells]) + " |"
        lines.append(row)
        print(row, flush=True)

    totals = [f"{sum(column)}/{len(items)}" for column in zip(*scores, strict=True)]
    summary = "| Total | " + " | ".join(totals) + " |"
    lines.append(summary)
    print(summary)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except (ConnectError, ConnectionError) as error:
        raise SystemExit(MODEL_ERROR) from error
    except ResponseError as error:
        if error.status_code != 404:
            raise
        raise SystemExit(MODEL_ERROR) from error
