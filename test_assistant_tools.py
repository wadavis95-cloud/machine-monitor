from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from assistant import tools
from assistant.eam import connect, load_predictions
from assistant.eam_contract import Asset
from assistant.seed import build_eam
from loader import load_data

DATA_DIR = Path(__file__).with_name("data")


@pytest.fixture
def ctx(tmp_path):
    db_path = tmp_path / "eam.sqlite"
    readings = load_data(DATA_DIR / "train_FD001.txt")
    predictions = load_predictions(DATA_DIR / "predictions_FD001.csv")
    build_eam(db_path, readings, predictions, seed=0)
    return tools.load_context(db_path, DATA_DIR)


@pytest.fixture
def conn(ctx):
    with closing(connect(ctx.db_path)) as connection:
        yield connection


def _current_cycle(conn, unit):
    return conn.execute(
        "SELECT current_cycle FROM machines WHERE unit = ?", (unit,)
    ).fetchone()["current_cycle"]


def test_fleet_status_sorted_by_rul_then_flag(ctx, conn, monkeypatch):
    # Give only these four engines estimates so they sort ahead of missing RULs.
    monkeypatch.setattr(ctx, "predictions", {})
    cases = [
        (1, 25, [15] * 10),
        (2, 25, [15] * 7 + [21] * 3),
        (3, 25, [15] * 5 + [21] * 5),
        (4, 10, [15] * 10),
    ]
    for unit, rul, t24 in cases:
        cycle = _current_cycle(conn, unit)
        ctx.predictions[unit, cycle] = {"rul_pred": rul, "split": "train"}
        ctx.bands[unit] = (10, 20)
        recent = (ctx.readings["unit"] == unit) & ctx.readings["cycle"].between(
            cycle - 9, cycle
        )
        ctx.readings.loc[recent, "s_2"] = t24

    rows = tools.fleet_status(ctx, top_n=4)

    assert len(rows) == 4
    assert [(row["unit"], row["rul"], row["flag"]) for row in rows] == [
        (4, 10, "none"),
        (3, 25, "red"),
        (2, 25, "yellow"),
        (1, 25, "none"),
    ]


def test_fleet_status_top_n_limits_rows(ctx):
    assert len(tools.fleet_status(ctx, top_n=3)) == 3


def test_tools_never_see_future_readings(ctx, conn):
    recent = tools.engine_detail(ctx, 1)["t24_recent"]

    assert recent
    assert recent[-1]["cycle"] == _current_cycle(conn, 1)


def test_parts_for_order_rule(ctx, conn, monkeypatch):
    cycle = _current_cycle(conn, 1)
    monkeypatch.setitem(ctx.predictions, (1, cycle), {"rul_pred": 25, "split": "train"})
    conn.executemany(
        "UPDATE parts SET lead_time_days = ?, on_hand = ? WHERE part_id = ?",
        [(20, 0, "P-HPC-01"), (10, 0, "P-HPC-02"), (20, 2, "P-HPC-03")],
    )
    conn.commit()

    rows = tools.parts_for(ctx, 1)

    assert rows
    by_id = {row["part_id"]: row["needs_order"] for row in rows}
    assert by_id["P-HPC-01"] is True
    assert by_id["P-HPC-02"] is False
    assert by_id["P-HPC-03"] is False


def test_missing_prediction_gives_none(ctx, conn, monkeypatch):
    monkeypatch.delitem(ctx.predictions, (1, _current_cycle(conn, 1)))

    rows = tools.fleet_status(ctx, top_n=100)
    parts = tools.parts_for(ctx, 1)

    assert len(rows) == 100
    assert rows[-1]["unit"] == 1
    assert rows[-1]["rul"] is None
    assert parts
    assert all(part["needs_order"] is None for part in parts)


def test_unknown_unit_returns_error(ctx):
    assert tools.engine_detail(ctx, 999) == {
        "error": "Unknown engine 999. Valid engines: 1-100."
    }


def test_work_orders_filters_by_status(ctx, conn):
    # Add an open order alongside engine 1's seeded closed order.
    conn.execute(
        "INSERT INTO work_orders (wo_id, unit, type, status) VALUES (?, ?, ?, ?)",
        ("WO-TEST", 1, "corrective", "open"),
    )
    conn.commit()

    orders = tools.work_orders(ctx, 1, status="open")

    assert len(orders) == 1
    assert orders[0]["wo_id"] == "WO-TEST"
    assert orders[0]["status"] == "open"


def test_work_orders_preserves_legacy_fields_and_values(ctx, conn):
    expected = [
        dict(row)
        for row in conn.execute(
            """SELECT wo_id, unit, type, symptom, action, parts_used, tech,
                      comments, opened, closed, status
               FROM work_orders WHERE unit = 2 ORDER BY wo_id"""
        )
    ]

    assert expected[0]["parts_used"] == "P-OIL-01"
    assert tools.work_orders(ctx, 2) == expected


def test_read_tools_use_injected_eam_and_prediction_split(tmp_path, monkeypatch):
    asset = Asset("ENG-001", "Engine 1", "Line 1", current_cycle=100)
    eam = SimpleNamespace(
        list_assets=lambda: [asset],
        get_asset=lambda asset_id: asset if asset_id == asset.asset_id else None,
        list_work_orders=lambda asset_id, status=None: [],
        list_parts=list,
    )
    monkeypatch.setattr(
        tools,
        "load_predictions",
        lambda path: {(1, 99): {"split": "val", "rul_pred": 7}},
    )
    db_path = tmp_path / "unused.sqlite"
    ctx = tools.load_context(db_path, DATA_DIR, eam=eam)

    fleet = tools.fleet_status(ctx)
    assert len(fleet) == 1
    assert fleet[0]["split"] == "val"
    assert fleet[0]["rul"] is None
    assert tools.engine_detail(ctx, 1)["split"] == "val"
    assert tools.parts_for(ctx, 1) == []
    assert tools.work_orders(ctx, 1) == []
    assert not db_path.exists()
