import json

import pytest
from langchain_core.messages import AIMessage

from assistant.scoring import chain_ok, drafts_ok, facts_ok, invented_ids, tools_ok
from evals.assistant_golden import golden_items
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


def test_eval_report_shows_evidence_only_for_failures(tmp_path, monkeypatch):
    answer = "Engine 3 and Engine 999.\n" + "x" * 600 + " yellow"

    call = _tool_call(args={"top_n": 100})
    model = EvalModel(
        call, AIMessage(content=answer), call, AIMessage(content="Engine 3")
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

    eval_assistant.main()

    markdown = report.read_text(encoding="utf-8")
    assert "| PM label | Chain | Overall |" in markdown
    assert "| Total | 2/2 | 1/2 | 1/2 | 2/2 | 2/2 | 2/2 | 1/2 | 1/2 |" in markdown
    assert "## Failures\n\n### failed-case" in markdown
    assert "### passed-case" not in markdown
    assert "**Question** Which engines should we inspect?" in markdown
    assert "**Expected facts** engine 3, engine 4, yellow" in markdown
    assert "**Missing facts** engine 4\n" in markdown
    assert "**Invented IDs** Engine 999" in markdown
    assert "**Tools called** fleet_status" in markdown
    preview = answer[:600].replace("\n", "\n    ")
    assert f"**Final answer**\n\n    {preview}…\n" in markdown
