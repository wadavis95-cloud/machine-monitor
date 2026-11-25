import re

ENGINE_LABEL = r"(?:engine|unit(?:\s+id)?)\s+(?P<unit>\d+)"
ENGINE_PATTERN = re.compile(rf"\b{ENGINE_LABEL}\b", re.IGNORECASE)

# Seeded work orders have numeric IDs. Drafts have 32 hexadecimal characters.
ID_PATTERN = re.compile(
    r"\b(?:WO-(?:[0-9a-f]{32}|\d+)|PR-[0-9a-f]{32}|P-[A-Z]+-\d+|"
    rf"{ENGINE_LABEL})\b",
    re.IGNORECASE,
)
UNIT_PATTERN = re.compile(
    r'"unit"\s*:\s*(?P<quote>"?)(?P<unit>\d+)(?P=quote)(?=\s*(?:[,}]|$))'
)


def tools_ok(called: list[str], expected: set[str]) -> bool:
    return expected.issubset(called)


def facts_ok(answer: str, facts: list[str]) -> bool:
    units = set(ENGINE_PATTERN.findall(answer))
    answer = answer.casefold()
    for fact in facts:
        engine = ENGINE_PATTERN.fullmatch(fact)
        matched = engine["unit"] in units if engine else fact.casefold() in answer
        if not matched:
            return False
    return True


def invented_ids(
    answer: str, tool_results_text: str, extra_reference_text: str = ""
) -> list[str]:
    def id_key(match: re.Match) -> str:
        unit = match["unit"]
        return f"engine {unit}" if unit else match.group().casefold()

    references = f"{tool_results_text}\n{extra_reference_text}"
    known = {id_key(match) for match in ID_PATTERN.finditer(references)}
    # Tool JSON can carry the unit as a number or a numeric string.
    known.update(
        f"engine {match['unit']}" for match in UNIT_PATTERN.finditer(references)
    )
    missing = {}
    for match in ID_PATTERN.finditer(answer):
        key = id_key(match)
        if key not in known:
            missing.setdefault(key, match.group())
    return list(missing.values())


def drafts_ok(drafts: list[str], should_draft: bool) -> bool:
    return bool(drafts) == should_draft
