from contextlib import closing
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from sqlite3 import Connection, Row
from uuid import uuid4

import pandas as pd

from assistant import rules
from assistant.eam import connect, load_predictions
from assistant.eam_contract import (
    Asset,
    Part,
    PartQuantity,
    PartRequest,
    StoreStock,
    WorkOrder,
)
from assistant.flags import t24_band
from loader import load_data


@dataclass
class FleetContext:
    db_path: Path
    readings: pd.DataFrame
    predictions: dict
    bands: dict[int, tuple[float, float]]
    drafts_made: list[str] = field(default_factory=list)


def _asset_id(unit: int) -> str:
    return f"ENG-{unit:03d}"


def _unit(asset_id: str) -> int:
    return int(asset_id.removeprefix("ENG-"))


@dataclass
class _DemoAsset(Asset):
    split: str | None = None


@dataclass
class _DemoWorkOrder(WorkOrder):
    symptom: str | None = None


class _DemoEAM:
    """Temporary mapping for the SQL that moves to the SQLite adapter in step 2."""

    def __init__(self, conn: Connection):
        self.conn = conn

    @staticmethod
    def _asset(row: Row) -> _DemoAsset:
        return _DemoAsset(
            asset_id=_asset_id(row["unit"]),
            name=f"Engine {row['unit']}",
            location=row["line"],
            current_cycle=row["current_cycle"],
            split=row["split"],
        )

    def list_assets(self) -> list[_DemoAsset]:
        rows = self.conn.execute(
            "SELECT unit, line, current_cycle, split FROM machines ORDER BY unit"
        )
        return [self._asset(row) for row in rows]

    def get_asset(self, asset_id: str) -> _DemoAsset | None:
        row = self.conn.execute(
            "SELECT unit, line, current_cycle, split FROM machines WHERE unit = ?",
            (_unit(asset_id),),
        ).fetchone()
        return None if row is None else self._asset(row)

    def list_parts(self) -> list[Part]:
        rows = self.conn.execute(
            "SELECT part_id, name, on_hand, lead_time_days, unit_cost FROM parts ORDER BY part_id"
        )
        return [
            Part(
                part_id=row["part_id"],
                name=row["name"],
                unit_of_measure="each",
                lead_time_days=row["lead_time_days"],
                unit_cost=row["unit_cost"],
                stock=[StoreStock(store="main", on_hand=row["on_hand"])],
            )
            for row in rows
        ]

    def list_work_orders(
        self, asset_id: str, status: str | None = None
    ) -> list[_DemoWorkOrder]:
        query = "SELECT * FROM work_orders WHERE unit = ?"
        params = (_unit(asset_id),)
        if status is not None:
            query += " AND status = ?"
            params += (status,)
        return [
            _DemoWorkOrder(
                wo_id=row["wo_id"],
                asset_id=asset_id,
                type=row["type"],
                status=row["status"],
                summary=row["action"],
                comments=row["comments"],
                assigned_to=row["tech"],
                parts=[]
                if row["parts_used"] is None
                else [PartQuantity(row["parts_used"], 1)],
                opened=row["opened"],
                closed=row["closed"],
                symptom=row["symptom"],
            )
            for row in self.conn.execute(query + " ORDER BY wo_id", params)
        ]

    # Sending and reference lookup are introduced after the draft lifecycle is split.
    def find_by_reference(self, ref: str) -> str | None:
        raise NotImplementedError

    def submit_work_request(self, order: WorkOrder, ref: str) -> str:
        raise NotImplementedError

    def submit_part_request(self, request: PartRequest, ref: str) -> str:
        raise NotImplementedError


def load_context(db_path: Path, data_dir: Path) -> FleetContext:
    """Load a fleet snapshot with readings through each engine's current cycle."""
    readings = load_data(data_dir / "train_FD001.txt")
    predictions = load_predictions(data_dir / "predictions_FD001.csv")
    with closing(connect(db_path)) as conn:
        current_cycles = {
            _unit(asset.asset_id): asset.current_cycle
            for asset in _DemoEAM(conn).list_assets()
        }

    # Each row is compared with its own engine's cutoff before bands are calculated.
    cutoff = readings["unit"].map(current_cycles)
    readings = readings.loc[readings["cycle"] <= cutoff].copy()
    bands = {unit: t24_band(readings, unit) for unit in current_cycles}
    return FleetContext(db_path, readings, predictions, bands)


def _unknown_engine(unit):
    return {"error": f"Unknown engine {unit}. Valid engines: 1-100."}


def _rul(ctx, asset: Asset):
    prediction = ctx.predictions.get((_unit(asset.asset_id), asset.current_cycle))
    return None if prediction is None else int(prediction["rul_pred"])


def _recent_readings(ctx, asset: Asset):
    readings = ctx.readings
    at_current_cycle = (readings["unit"] == _unit(asset.asset_id)) & (
        readings["cycle"] <= asset.current_cycle
    )
    recent = readings.loc[at_current_cycle, ["cycle", "s_2"]]
    return recent.sort_values("cycle").tail(10)


def _assess_engine(ctx, asset: Asset, recent):
    return rules.assess_engine(
        _rul(ctx, asset), recent["s_2"].tolist(), ctx.bands[_unit(asset.asset_id)]
    )


def _engine_status(asset: Asset, rul: int | None, flag: str) -> dict:
    return {
        "unit": _unit(asset.asset_id),
        "rul": rul,
        "flag": flag,
        "current_cycle": asset.current_cycle,
        "split": asset.split if isinstance(asset, _DemoAsset) else None,
    }


def fleet_status(ctx: FleetContext, top_n: int = 5) -> list[dict]:
    """Return up to top_n engines ranked by remaining life, then warning severity.

    One cycle equals one day. Missing life estimates are null and rank last.
    """

    def assess(asset: Asset) -> tuple[int | None, str]:
        return _assess_engine(ctx, asset, _recent_readings(ctx, asset))

    with closing(connect(ctx.db_path)) as conn:
        ranked = rules.rank_fleet(_DemoEAM(conn), assess, top_n)
    return [_engine_status(asset, rul, flag) for asset, rul, flag in ranked]


def engine_detail(ctx: FleetContext, unit: int) -> dict:
    """Return one engine's life estimate, warning, last ten T24 readings, and open order IDs.

    One cycle equals one day. A null RUL means the estimate is missing.
    """
    with closing(connect(ctx.db_path)) as conn:
        eam = _DemoEAM(conn)
        asset = eam.get_asset(_asset_id(unit))
        if asset is None:
            return _unknown_engine(unit)
        order_ids = rules.open_work_order_ids(eam, asset)

    recent = _recent_readings(ctx, asset)
    detail = _engine_status(asset, *_assess_engine(ctx, asset, recent))
    detail["t24_recent"] = [
        {"cycle": int(cycle), "t24": float(t24) if isfinite(t24) else None}
        for cycle, t24 in recent.itertuples(index=False, name=None)
    ]
    detail["open_work_orders"] = order_ids
    return detail


def parts_for(ctx: FleetContext, unit: int) -> list[dict] | dict:
    """Return stock, lead times in days, and whether each part needs ordering.

    One cycle equals one day. A null order decision means the life estimate is missing.
    """
    with closing(connect(ctx.db_path)) as conn:
        eam = _DemoEAM(conn)
        asset = eam.get_asset(_asset_id(unit))
        if asset is None:
            return _unknown_engine(unit)
        results = rules.assess_parts(eam, _rul(ctx, asset))

    return [
        {
            "part_id": part.part_id,
            "name": part.name,
            "on_hand": on_hand,
            "lead_time_days": part.lead_time_days,
            "needs_order": needs_order,
        }
        for part, on_hand, needs_order in results
    ]


def work_orders(
    ctx: FleetContext, unit: int, status: str | None = None
) -> list[dict] | dict:
    """Return an engine's work orders, optionally filtered by status, with calendar dates."""
    with closing(connect(ctx.db_path)) as conn:
        eam = _DemoEAM(conn)
        asset = eam.get_asset(_asset_id(unit))
        if asset is None:
            return _unknown_engine(unit)
        orders = eam.list_work_orders(asset.asset_id, status)

    return [
        {
            "wo_id": order.wo_id,
            "unit": unit,
            "type": order.type,
            "symptom": order.symptom,
            "action": order.summary,
            "parts_used": order.parts[0].part_id if order.parts else None,
            "tech": order.assigned_to,
            "comments": order.comments,
            "opened": order.opened,
            "closed": order.closed,
            "status": order.status,
        }
        for order in orders
    ]


def draft_work_order(ctx: FleetContext, unit: int, summary: str, reason: str) -> dict:
    """Save a work order draft for a person to review."""
    error = rules.draft_error(len(ctx.drafts_made))
    if error is not None:
        return {"error": error}

    draft_id = f"WO-{uuid4().hex}"
    with closing(connect(ctx.db_path)) as conn, conn:
        if _DemoEAM(conn).get_asset(_asset_id(unit)) is None:
            return _unknown_engine(unit)
        conn.execute(
            """
            INSERT INTO work_orders (wo_id, unit, type, action, comments, status)
            VALUES (?, ?, 'corrective', ?, ?, 'draft')
            """,
            (draft_id, unit, summary, reason),
        )

    ctx.drafts_made.append(draft_id)
    return {"draft_id": draft_id}


def draft_part_request(ctx: FleetContext, part_id: str, qty: int, reason: str) -> dict:
    """Save a part request draft for a person to review."""
    error = rules.draft_error(len(ctx.drafts_made), qty)
    if error is not None:
        return {"error": error}

    draft_id = f"PR-{uuid4().hex}"
    with closing(connect(ctx.db_path)) as conn, conn:
        part = conn.execute(
            "SELECT 1 FROM parts WHERE part_id = ?", (part_id,)
        ).fetchone()
        if part is None:
            return {"error": f"Unknown part {part_id}."}
        conn.execute(
            """
            INSERT INTO part_requests (pr_id, part_id, qty, reason, status, created_by)
            VALUES (?, ?, ?, ?, 'draft', 'assistant')
            """,
            (draft_id, part_id, qty, reason),
        )

    ctx.drafts_made.append(draft_id)
    return {"draft_id": draft_id}
