from contextlib import closing

import pytest

from assistant.eam import connect, create_schema
from assistant.eam_contract import EAM, Asset, Part, PartQuantity, StoreStock, WorkOrder
from assistant.sqlite_eam import SQLiteEAM


def sqlite_adapter(tmp_path) -> EAM:
    db_path = tmp_path / "eam.sqlite"
    with closing(connect(db_path)) as conn, conn:
        create_schema(conn)
        conn.executescript("""
            INSERT INTO machines (unit, line, area, current_cycle, split)
            VALUES (1, 'Line 1', 'Area 1', 100, 'train'),
                   (2, 'Line 2', 'Area 1', 80, NULL);

            INSERT INTO parts (part_id, name, subsystem, on_hand, lead_time_days, unit_cost)
            VALUES ('P-1', 'Seal', 'Oil', 4, 12, 20.5);

            INSERT INTO work_orders (wo_id, unit, type, symptom, action, parts_used,
                                     tech, comments, opened, closed, status)
            VALUES ('WO-1', 1, 'corrective', 'Leaking seal', 'Replaced seal', 'P-1',
                    'AK', 'Pressure held on retest', '2026-01-01', '2026-01-02', 'closed'),
                   ('WO-2', 1, 'corrective', NULL, NULL, NULL,
                    NULL, 'Watch pressure', NULL, NULL, 'open'),
                   ('WO-3', 2, 'corrective', NULL, NULL, NULL,
                    NULL, NULL, NULL, NULL, 'open');
            """)
    return SQLiteEAM(db_path)


# Add another adapter factory backed by the same logical records here.
@pytest.fixture(params=[pytest.param(sqlite_adapter, id="sqlite")])
def eam_adapter(request, tmp_path) -> EAM:
    return request.param(tmp_path)


def test_asset_lookup_matches_asset_listing(eam_adapter):
    assets = {asset.asset_id: asset for asset in eam_adapter.list_assets()}
    assert assets == {
        "ENG-001": Asset("ENG-001", "Engine 1", "Line 1", current_cycle=100),
        "ENG-002": Asset("ENG-002", "Engine 2", "Line 2", current_cycle=80),
    }
    assert all(type(asset) is Asset for asset in assets.values())
    assert eam_adapter.get_asset("ENG-001") == assets["ENG-001"]


def test_unknown_asset_has_no_record_or_work_orders(eam_adapter):
    assert eam_adapter.get_asset("ENG-999") is None
    assert not eam_adapter.list_work_orders("ENG-999")


def test_parts_expose_stock_by_store(eam_adapter):
    assert list(eam_adapter.list_parts()) == [
        Part("P-1", "Seal", "each", 12, 20.5, [StoreStock("main", 4)])
    ]


def test_work_orders_filter_by_asset_and_status(eam_adapter):
    orders = {order.wo_id: order for order in eam_adapter.list_work_orders("ENG-001")}
    assert set(orders) == {"WO-1", "WO-2"}
    assert type(orders["WO-1"]) is WorkOrder
    assert orders["WO-1"] == WorkOrder(
        "WO-1",
        "ENG-001",
        "corrective",
        "closed",
        summary="Replaced seal",
        problem_description="Leaking seal",
        comments="Pressure held on retest",
        assigned_to="AK",
        parts=[PartQuantity("P-1", 1)],
        opened="2026-01-01",
        closed="2026-01-02",
    )
    assert list(eam_adapter.list_work_orders("ENG-001", status="open")) == [
        orders["WO-2"]
    ]
    assert not eam_adapter.list_work_orders("ENG-001", status="draft")
