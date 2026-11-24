import re


def finalize_answer(answer: str, tool_calls: list[dict], draft_ids: list[str]) -> str:
    """Append sources and a note when a draft claim lacks a saved part request."""
    tools = dict.fromkeys(call["name"] for call in tool_calls)
    footer = []
    if tools:
        sources = " ".join(f"[{name}]" for name in tools)
        footer.append(f"Sources: {sources}")

    # A draft tool can fail, so only a saved draft ID (WO- or PR-) proves one exists.
    # Match "drafted" only: "Shall I draft one?" is an offer, not a claim.
    if not draft_ids and re.search(r"\bdrafted\b", answer, re.IGNORECASE):
        footer.append("Note: no drafts were created in this run.")

    return answer + "\n\n" + "\n".join(footer) if footer else answer
