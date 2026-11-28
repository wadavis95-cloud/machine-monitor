"""Translate between engine asset IDs and numeric sensor and SQLite keys."""

ENGINE_PREFIX = "ENG-"


def asset_id_for_unit(unit: int) -> str:
    return f"{ENGINE_PREFIX}{unit:03d}"


def unit_for_asset_id(asset_id: str) -> int:
    unit = int(asset_id.removeprefix(ENGINE_PREFIX))
    if asset_id != asset_id_for_unit(unit):
        raise ValueError(f"Invalid engine asset ID: {asset_id!r}")
    return unit
