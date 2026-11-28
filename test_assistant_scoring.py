import json
from contextlib import contextmanager

import httpx
import pytest
from langchain_core.messages import AIMessage

from assistant.hexagon_eam import HexagonEAM
from assistant.scoring import chain_ok, drafts_ok, facts_ok, invented_ids, tools_ok
from evals.assistant_golden import golden_items
from mock_hexagon.app import create_app as create_mock_app
from scripts import eval_assistant
from test_assistant_graph import ScriptedModel, _tool_call


class EvalModel(ScriptedModel):
    model = "scripted"

    def bind_tools(self, tools):
        return self


def test_tools_ok_requires_every_expected_call():
    assert tools_ok(
        ["fleet_status", "parts_for", "engine_detail"], {"fleet_status", "parts_for"}
    )
    assert not tools_ok(["fleet_status"], {"fleet_status", "parts_for"})


def test_chain_ok_accepts_parts_calls_for_every_expected_unit():
    calls = [
        {"name": "parts_for", "args": {"unit": 27}},
        {"name": "parts_for", "args": {"unit": "39"}},
        {"name": "parts_for", "args": {"unit": 74}},
    ]
    assert chain_ok(calls, {27, 39, 74})


def test_chain_ok_rejects_a_missing_parts_lookup():
    calls = [
        {"name": "parts_for", "args": {"unit": 27}},
        {"name": "parts_for", "args": {"unit": 27}},
        {"name": "parts_for", "args": {"unit": 74}},
        {"name": "engine_detail", "args": {"unit": 39}},
    ]
    assert not chain_ok(calls, {27, 39, 74})


def test_chain_ok_passes_without_expected_units():
    assert chain_ok([], None)


def test_facts_ok_requires_every_substring():
    assert facts_ok("Engine 3 has 21 days left.", ["engine 3", "21 days"])
    assert not facts_ok("Engine 3 has 21 days left.", ["engine 3", "yellow"])
    assert facts_ok("No facts required.", [])


@pytest.mark.parametrize(
    ("answer", "facts", "expected"),
    [
        ("The engine with unit ID 27 is most at risk.", ["engine 27"], True),
        (
            "1. Unit 27 (RUL: 6)\n2. Unit 39 (RUL: 11)\n3. Unit 74 (RUL: 11)",
            ["engine 27", "engine 39", "engine 74"],
            True,
        ),
        ("UNIT ID 27", ["ENGINE 27"], True),
        ("Engine 270, Unit 270, unit ID 270", ["engine 27"], False),
    ],
)
def test_facts_ok_matches_engine_labels_and_full_numbers(answer, facts, expected):
    assert facts_ok(answer, facts) is expected


def test_invented_ids_flags_wo_not_in_results():
    assert invented_ids("See WO-101 and WO-101.", "WO-1010") == ["WO-101"]


def test_invented_ids_allows_cited_ids():
    wo_draft = "WO-1234567890abcdef1234567890abcdef"
    pr_draft = "PR-a234567890abcdef1234567890abcdef"
    results = json.dumps(
        {"unit": 3, "part_id": "P-HPC-01", "ids": ["WO-101", wo_draft, pr_draft]}
    )
    answer = f"Engine 3: WO-101, P-HPC-01, {wo_draft}, and {pr_draft}."
    assert invented_ids(answer, results) == []


def test_invented_ids_flags_unsupported_parts_engines_and_uuid_drafts():
    answer = "Engine 3 uses P-HPC-01. Drafted PR-a234567890abcdef1234567890abcdef."
    results = '{"unit": 30, "rul": 3, "part_id": "P-HPC-010"}'
    assert invented_ids(answer, results) == [
        "Engine 3",
        "P-HPC-01",
        "PR-a234567890abcdef1234567890abcdef",
    ]


def test_invented_ids_matches_engine_aliases_in_the_question():
    assert invented_ids(
        "Engine 27, unit ID 999 and P-XYZ-99.",
        "",
        "Which parts should we order for Unit 27?",
    ) == ["unit ID 999", "P-XYZ-99"]


@pytest.mark.parametrize(
    ("case", "question", "tool", "args", "answer", "unknown"),
    [
        (
            "engine-parts",
            None,
            "parts_for",
            {"unit": 27},
            "Parts needing ordering for engine 27: P-HPC-01 and P-LPT-01.",
            "",
        ),
        (
            "lead-time",
            None,
            "parts_for",
            {"unit": 27},
            "The lead time in days for part P-HPC-01 for engine 27 is **35 days**.",
            "",
        ),
        (
            "engine-parts",
            "Which parts need ordering? Include part IDs.",
            "parts_for",
            {"unit": "27"},
            "Parts needing ordering for engine 27: P-HPC-01 and P-LPT-01.",
            "",
        ),
        (
            "draft-part",
            None,
            "draft_part_request",
            {"part_id": "P-HPC-01", "qty": 1, "reason": "upcoming service"},
            "The part request for 1 P-HPC-01 has been drafted.",
            "",
        ),
        (
            "draft-part",
            "Draft a request for one compressor seal kit.",
            "draft_part_request",
            {"part_id": "P-HPC-01", "qty": 1, "reason": "upcoming service"},
            "The part request for 1 P-HPC-01 has been drafted.",
            "",
        ),
        (
            "lead-time",
            None,
            "parts_for",
            {"unit": 27},
            "The lead time for P-HPC-01 for engine 27 is 35 days. See engine 999 and P-XYZ-99.",
            "engine 999, P-XYZ-99",
        ),
    ],
)
def test_eval_ids_use_question_and_tool_args(
    ctx, case, question, tool, args, answer, unknown
):
    item = next(item for item in golden_items(ctx) if item["id"] == case)
    if question is not None:
        item["question"] = question
    model = EvalModel(_tool_call(tool, args), AIMessage(content=answer))

    checks, failure = eval_assistant.score_item(item, ctx, model)

    assert checks[2] is (not unknown)
    if unknown:
        assert f"- **Invented IDs** {unknown}" in failure


def test_drafts_ok_checks_presence_against_intent():
    assert drafts_ok(["WO-101"], True)
    assert drafts_ok([], False)
    assert not drafts_ok([], True)
    assert not drafts_ok(["WO-101"], False)


def test_sources_ok_accepts_live_rank_one_answer_with_tool_suggestion():
    answer = (
        "The engine most at risk is **unit 27** with a remaining life (RUL) of 6 cycles "
        'and a "red" warning flag. It has the shortest RUL among the top 3 high-risk engines. '
        "For detailed diagnostics, check `engine_detail` for unit 27."
    )
    assert eval_assistant.sources_ok(
        answer, ["fleet_status"], {"fleet_status", "engine_detail"}
    )


def test_sources_ok_accepts_live_rank_three_answer_with_tool_suggestion():
    answer = """The top 3 engines with red flags (highest risk) for the next PM are:

1. **Unit 27**
   - RUL: 6 cycles
   - T24 recent: Stable around 643.3-644.0
   - Open work order: WO-1027

2. **Unit 39**
   - RUL: 11 cycles
   - T24 recent: Stable around 643.2-643.9
   - Open work order: WO-1039

3. **Unit 74**
   - RUL: 11 cycles
   - T24 recent: Stable around 642.3-643.6
   - No open work orders

**Next steps**:
- Prioritize units with lower RUL (e.g., Unit 27).
- Check if parts are needed for these units using `parts_for`.
- Review active work orders (WO-1027, WO-1039) fo…"""
    assert eval_assistant.sources_ok(
        answer,
        ["fleet_status", "engine_detail"],
        {"fleet_status", "engine_detail", "parts_for"},
    )


@pytest.mark.parametrize(
    "citation",
    [
        "Sources: fleet_status, engine_detail",
        "**Sources:** `engine_detail`",
        "Check [engine_detail] for details.",
    ],
)
def test_sources_ok_rejects_citations_for_uncalled_tools(citation):
    assert not eval_assistant.sources_ok(
        f"Engine 27 is most at risk.\n{citation}",
        ["fleet_status"],
        {"fleet_status", "engine_detail"},
    )


def test_eval_report_shows_evidence_only_for_failures(tmp_path, monkeypatch):
    answer = "Engine 3 and Engine 999.\n" + "x" * 600 + " yellow"

    call = _tool_call(args={"top_n": 100})
    model = EvalModel(
        *(call, AIMessage(content=answer), call, AIMessage(content="Engine 3")) * 2
    )
    items = [
        {
            "id": "failed-case",
            "question": "Which engines should we inspect?",
            "expect_tools": {"fleet_status"},
            "expected_facts": lambda ctx: ["engine 3", "engine 4", "yellow"],
            "should_draft": False,
            "expect_units": {3},
        },
        {
            "id": "passed-case",
            "question": "Which engine is ready?",
            "expect_tools": {"fleet_status"},
            "expected_facts": lambda ctx: ["engine 3"],
            "should_draft": False,
        },
    ]
    report = tmp_path / "assistant_eval.md"
    monkeypatch.setattr(eval_assistant, "REPORT", report)
    monkeypatch.setattr(eval_assistant, "chat_model_factory", lambda: model)
    monkeypatch.setattr(eval_assistant, "golden_items", lambda ctx: items)

    lifecycle = []

    @contextmanager
    def in_process_mock():
        lifecycle.append("start")
        mock = create_mock_app(
            api_key="test-key", mode="normal", ignore_idempotency=False
        )
        try:
            yield HexagonEAM(
                "http://mock", "test-key", transport=httpx.WSGITransport(app=mock)
            )
        finally:
            lifecycle.append("stop")

    monkeypatch.setattr(eval_assistant, "serve_mock", in_process_mock)
    ticks = iter([0, 1, 3, 4, 9, 10, 20, 21, 22, 23, 27, 31])
    monkeypatch.setattr(eval_assistant, "perf_counter", lambda: next(ticks))
    eval_assistant.main()

    assert lifecycle == ["start", "stop"]
    assert model.replies == []
    markdown = report.read_text(encoding="utf-8")
    assert "| PM label | Chain | Overall | Duration (s) |" in markdown
    assert markdown.index("## SQLite") < markdown.index("## Hexagon")
    sqlite, hexagon = markdown.split("## Hexagon")
    totals = "| Total | 2/2 | 1/2 | 1/2 | 2/2 | 2/2 | 2/2 | 1/2 | 1/2 |"
    for section, failed, passed, duration in (
        (sqlite, "2.00", "5.00", "10.00"),
        (hexagon, "1.00", "4.00", "11.00"),
    ):
        assert (
            f"| failed-case | pass | fail | fail | pass | pass | pass | fail | fail | {failed} |"
            in section
        )
        assert (
            f"| passed-case | pass | pass | pass | pass | pass | pass | pass | pass | {passed} |"
            in section
        )
        assert f"{totals} {duration} |" in section
    assert markdown.count("### Failures\n\n#### failed-case") == 2
    assert "#### passed-case" not in markdown
    assert "**Question** Which engines should we inspect?" in markdown
    assert "**Expected facts** engine 3, engine 4, yellow" in markdown
    assert "**Missing facts** engine 4\n" in markdown
    assert "**Invented IDs** Engine 999" in markdown
    assert "**Tools called** fleet_status" in markdown
    preview = answer[:600].replace("\n", "\n    ")
    assert f"**Final answer**\n\n    {preview}…\n" in markdown


@pytest.mark.parametrize("adapter", ["sqlite", "hexagon"])
def test_eval_cli_filters_cases_and_only_starts_mock_for_hexagon(
    tmp_path, monkeypatch, adapter
):
    runs = []
    lifecycle = []
    remote_eam = object()

    @contextmanager
    def in_process_mock():
        lifecycle.append("started")
        try:
            yield remote_eam
        finally:
            lifecycle.append("stopped")

    def run_adapter(name, db_path, items, expected, model, *, eam=None):
        runs.append((name, [item["id"] for item in items], list(expected), eam))
        return []

    monkeypatch.setattr(eval_assistant, "REPORT", tmp_path / "filtered.md")
    monkeypatch.setattr(eval_assistant, "chat_model_factory", EvalModel)
    monkeypatch.setattr(eval_assistant, "_run_adapter", run_adapter)
    monkeypatch.setattr(eval_assistant, "serve_mock", in_process_mock)

    eval_assistant.main(["--adapter", adapter, "--only", "rank-3,rank-1", "engine-rul"])

    ids = ["rank-1", "rank-3", "engine-rul"]
    if adapter == "sqlite":
        assert runs == [("SQLite", ids, ids, None)]
        assert lifecycle == []
    else:
        assert runs == [("Hexagon", ids, ids, remote_eam)]
        assert lifecycle == ["started", "stopped"]


def test_eval_cli_rejects_unknown_case_before_starting_model(monkeypatch, capsys):
    monkeypatch.setattr(
        eval_assistant, "chat_model_factory", lambda: pytest.fail("Model started")
    )
    with pytest.raises(SystemExit) as error:
        eval_assistant.main(["--only", "rank-1,typo"])
    assert error.value.code == 2
    assert "unknown case IDs: typo" in capsys.readouterr().err
