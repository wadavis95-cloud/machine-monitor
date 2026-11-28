"""Maintenance decisions made from the shared data shapes."""

from collections.abc import Callable

from assistant.eam_contract import EAM, Asset, Part

ORDER_BUFFER_DAYS = 10
FLAG_RANK = {"red": 0, "yellow": 1, "none": 2}
MAX_DRAFTS = 3


def rank_fleet(
    eam: EAM,
    assess: Callable[[Asset], tuple[int | None, str]],
    top_n: int,
) -> list[tuple[Asset, int | None, str]]:
    rows = [(asset, *assess(asset)) for asset in eam.list_assets()]
    rows.sort(key=lambda row: (row[1] is None, row[1] or 0, FLAG_RANK[row[2]]))
    return rows[: max(0, top_n)]


def open_work_order_ids(eam: EAM, asset: Asset) -> list[str]:
    return [
        order.wo_id for order in eam.list_work_orders(asset.asset_id, status="open")
    ]


def needs_order(part: Part, on_hand: int, rul: int | None) -> bool | None:
    if rul is None:
        return None
    return on_hand == 0 and part.lead_time_days >= rul - ORDER_BUFFER_DAYS


def assess_parts(eam: EAM, rul: int | None) -> list[tuple[Part, int, bool | None]]:
    results = []
    for part in eam.list_parts():
        on_hand = sum(stock.on_hand for stock in part.stock)
        results.append((part, on_hand, needs_order(part, on_hand, rul)))
    return results


def draft_error(draft_count: int, qty: int = 1) -> str | None:
    if draft_count >= MAX_DRAFTS:
        return "Draft limit reached (3 per question)."
    if qty < 1:
        return "Quantity must be at least 1."
    return None
