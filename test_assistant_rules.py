from types import SimpleNamespace

from assistant import rules
from assistant.eam_contract import Asset, Part, StoreStock


def test_rank_fleet_preserves_input_order_for_ties_and_puts_missing_rul_last():
    assets = [
        Asset(f"ENG-{number:03d}", f"Engine {number}", "Line 1", current_cycle=100)
        for number in (2, 1, 3, 4)
    ]
    eam = SimpleNamespace(list_assets=lambda: assets)
    assessments = {
        "ENG-002": (10, "none"),
        "ENG-001": (10, "none"),
        "ENG-003": (None, "red"),
        "ENG-004": (10, "yellow"),
    }

    def assess(asset):
        return assessments[asset.asset_id]

    ranked = rules.rank_fleet(eam, assess, top_n=4)

    assert [asset.asset_id for asset, _, _ in ranked] == [
        "ENG-004",
        "ENG-002",
        "ENG-001",
        "ENG-003",
    ]


def test_assess_parts_uses_total_stock_and_inclusive_lead_time():
    empty = Part("P-1", "Seal", "each", 15, 20, [StoreStock("main", 0)])
    available = Part(
        "P-2",
        "Bearing",
        "each",
        15,
        20,
        [StoreStock("main", 0), StoreStock("backup", 2)],
    )
    eam = SimpleNamespace(list_parts=lambda: [empty, available])

    assert rules.assess_parts(eam, rul=25) == [(empty, 0, True), (available, 2, False)]
    assert rules.assess_parts(eam, rul=None) == [(empty, 0, None), (available, 2, None)]
