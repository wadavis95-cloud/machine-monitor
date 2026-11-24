import pytest


@pytest.fixture
def finalize():
    from assistant.guardrails import finalize_answer

    return finalize_answer


def test_sources_follow_first_call_order_without_duplicates(finalize):
    calls = [{"name": name} for name in ("fleet_status", "parts_for", "fleet_status")]
    assert finalize("Check these units.", calls, []) == (
        "Check these units.\n\nSources: [fleet_status] [parts_for]"
    )


def test_answer_without_tools_has_no_sources_line(finalize):
    assert finalize("I have no data.", [], []) == "I have no data."


@pytest.mark.parametrize("word", ["DRAFTED", "Drafted"])
def test_draft_claim_without_a_saved_id_gets_a_note(finalize, word):
    assert finalize(f"Request {word}.", [], []) == (
        f"Request {word}.\n\nNote: no drafts were created in this run."
    )


def test_call_without_a_saved_id_still_gets_a_note(finalize):
    calls = [{"name": "draft_part_request"}]
    assert finalize("Request drafted.", calls, []) == (
        "Request drafted.\n\nSources: [draft_part_request]"
        "\nNote: no drafts were created in this run."
    )


def test_saved_work_order_needs_no_note(finalize):
    calls = [{"name": "draft_work_order"}]
    assert finalize("Work order drafted.", calls, ["WO-123"]) == (
        "Work order drafted.\n\nSources: [draft_work_order]"
    )


def test_offer_to_draft_is_not_a_claim(finalize):
    answer = "Would you like me to draft a request?"
    assert finalize(answer, [], []) == answer


def test_saved_part_request_needs_no_note(finalize):
    calls = [{"name": "draft_part_request"}]
    assert finalize("Request drafted.", calls, ["PR-123"]) == (
        "Request drafted.\n\nSources: [draft_part_request]"
    )
