import json

from assistant.scoring import drafts_ok, facts_ok, invented_ids, tools_ok


def test_tools_ok_requires_every_expected_call():
    assert tools_ok(
        ["fleet_status", "parts_for", "engine_detail"], {"fleet_status", "parts_for"}
    )
    assert not tools_ok(["fleet_status"], {"fleet_status", "parts_for"})


def test_facts_ok_requires_every_substring():
    assert facts_ok("Engine 3 has 21 days left.", ["engine 3", "21 days"])
    assert not facts_ok("Engine 3 has 21 days left.", ["engine 3", "yellow"])
    assert facts_ok("No facts required.", [])


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


def test_drafts_ok_checks_presence_against_intent():
    assert drafts_ok(["WO-101"], True)
    assert drafts_ok([], False)
    assert not drafts_ok([], True)
    assert not drafts_ok(["WO-101"], False)
