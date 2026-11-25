import re

# Seeded work orders have numeric IDs. Drafts have 32 hexadecimal characters.
ID_PATTERN = re.compile(
    r"\b(?:WO-(?:[0-9a-f]{32}|\d+)|PR-[0-9a-f]{32}|P-[A-Z]+-\d+|engine\s+\d+)\b",
    re.IGNORECASE,
)
UNIT_PATTERN = re.compile(r'"unit"\s*:\s*(\d+)\b')


def tools_ok(called: list[str], expected: set[str]) -> bool:
    return expected.issubset(called)


def facts_ok(answer: str, facts: list[str]) -> bool:
    answer = answer.casefold()
    return all(fact.casefold() in answer for fact in facts)


def invented_ids(answer: str, tool_results_text: str) -> list[str]:
    def id_key(citation: str) -> str:
        return " ".join(citation.casefold().split())

    returned = {
        id_key(match.group()) for match in ID_PATTERN.finditer(tool_results_text)
    }
    # Tool JSON represents an engine as "unit": 3 rather than "engine 3".
    returned.update(
        f"engine {unit}" for unit in UNIT_PATTERN.findall(tool_results_text)
    )
    missing = {}
    for match in ID_PATTERN.finditer(answer):
        citation = match.group()
        key = id_key(citation)
        if key not in returned:
            missing.setdefault(key, citation)
    return list(missing.values())


def drafts_ok(drafts: list[str], should_draft: bool) -> bool:
    return bool(drafts) == should_draft
