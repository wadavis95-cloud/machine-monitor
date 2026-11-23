from contextlib import closing
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path

import pandas as pd

from assistant.eam import connect, load_predictions
from assistant.flags import flag_level, t24_band
from loader import load_data

ORDER_BUFFER_DAYS = 10
FLAG_RANK = {"red": 0, "yellow": 1, "none": 2}


@dataclass
class FleetContext:
    db_path: Path
    readings: pd.DataFrame
    predictions: dict
    bands: dict[int, tuple[float, float]]
    drafts_made: list[str] = field(default_factory=list)


def load_context(db_path: Path, data_dir: Path) -> FleetContext:
    """Load a fleet snapshot with readings through each engine's current cycle."""
    readings = load_data(data_dir / "train_FD001.txt")
    predictions = load_predictions(data_dir / "predictions_FD001.csv")
    with closing(connect(db_path)) as conn:
        current_cycles = dict(conn.execute("SELECT unit, current_cycle FROM machines"))

    # Each row is compared with its own engine's cutoff before bands are calculated.
    cutoff = readings["unit"].map(current_cycles)
    readings = readings.loc[readings["cycle"] <= cutoff].copy()
    bands = {unit: t24_band(readings, unit) for unit in current_cycles}
    return FleetContext(db_path, readings, predictions, bands)


def _machine(conn, unit):
    return conn.execute(
        "SELECT unit, current_cycle, split FROM machines WHERE unit = ?", (unit,)
    ).fetchone()


def _unknown_engine(unit):
    return {"error": f"Unknown engine {unit}. Valid engines: 1-100."}


def _rul(ctx, machine):
    prediction = ctx.predictions.get((machine["unit"], machine["current_cycle"]))
    return None if prediction is None else int(prediction["rul_pred"])


def _recent_readings(ctx, machine):
    readings = ctx.readings
    at_current_cycle = (readings["unit"] == machine["unit"]) & (
        readings["cycle"] <= machine["current_cycle"]
    )
    recent = readings.loc[at_current_cycle, ["cycle", "s_2"]]
    return recent.sort_values("cycle").tail(10)


def _engine_status(ctx, machine, recent):
    unit = machine["unit"]
    return {
        "unit": unit,
        "rul": _rul(ctx, machine),
        "flag": flag_level(recent["s_2"].tolist(), *ctx.bands[unit]),
        "current_cycle": machine["current_cycle"],
        "split": machine["split"],
    }


def fleet_status(ctx: FleetContext, top_n: int = 5) -> list[dict]:
    """Return up to top_n engines ranked by remaining life, then warning severity.

    One cycle equals one day. Missing life estimates are null and rank last.
    """
    with closing(connect(ctx.db_path)) as conn:
        machines = conn.execute(
            "SELECT unit, current_cycle, split FROM machines ORDER BY unit"
        ).fetchall()
    rows = [
        _engine_status(ctx, machine, _recent_readings(ctx, machine))
        for machine in machines
    ]
    rows.sort(
        key=lambda row: (row["rul"] is None, row["rul"] or 0, FLAG_RANK[row["flag"]])
    )
    return rows[: max(0, top_n)]


def engine_detail(ctx: FleetContext, unit: int) -> dict:
    """Return one engine's life estimate, warning, last ten T24 readings, and open order IDs.

    One cycle equals one day. A null RUL means the estimate is missing.
    """
    with closing(connect(ctx.db_path)) as conn:
        machine = _machine(conn, unit)
        if machine is None:
            return _unknown_engine(unit)
        orders = conn.execute(
            "SELECT wo_id FROM work_orders WHERE unit = ? AND status = 'open' ORDER BY wo_id",
            (unit,),
        ).fetchall()

    recent = _recent_readings(ctx, machine)
    detail = _engine_status(ctx, machine, recent)
    detail["t24_recent"] = [
        {"cycle": int(cycle), "t24": float(t24) if isfinite(t24) else None}
        for cycle, t24 in recent.itertuples(index=False, name=None)
    ]
    detail["open_work_orders"] = [order["wo_id"] for order in orders]
    return detail


def parts_for(ctx: FleetContext, unit: int) -> list[dict] | dict:
    """Return stock, lead times in days, and whether each part needs ordering.

    One cycle equals one day. A null order decision means the life estimate is missing.
    """
    with closing(connect(ctx.db_path)) as conn:
        machine = _machine(conn, unit)
        if machine is None:
            return _unknown_engine(unit)
        parts = conn.execute(
            "SELECT part_id, name, on_hand, lead_time_days FROM parts ORDER BY part_id"
        ).fetchall()

    rul = _rul(ctx, machine)
    results = []
    for part in parts:
        row = dict(part)
        row["needs_order"] = None
        if rul is not None:
            row["needs_order"] = (
                part["on_hand"] == 0
                and part["lead_time_days"] >= rul - ORDER_BUFFER_DAYS
            )
        results.append(row)
    return results


def work_orders(
    ctx: FleetContext, unit: int, status: str | None = None
) -> list[dict] | dict:
    """Return an engine's work orders, optionally filtered by status, with calendar dates."""
    with closing(connect(ctx.db_path)) as conn:
        if _machine(conn, unit) is None:
            return _unknown_engine(unit)
        query = "SELECT * FROM work_orders WHERE unit = ?"
        params = (unit,)
        if status is not None:
            query += " AND status = ?"
            params = (unit, status)
        return [dict(row) for row in conn.execute(query + " ORDER BY wo_id", params)]
