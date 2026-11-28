from dataclasses import asdict, dataclass, field
from functools import wraps
from math import isfinite
from pathlib import Path

import pandas as pd

from assistant import rules
from assistant.asset_ids import asset_id_for_unit, unit_for_asset_id
from assistant.drafts import DraftStore, draft_path_for
from assistant.eam import load_predictions
from assistant.eam_contract import (
    EAM,
    EAM_UNAVAILABLE_MESSAGE,
    Asset,
    EAMUnavailable,
    PartRequest,
    PartRequestLine,
    WorkOrder,
)
from assistant.evidence import capture_evidence
from assistant.flags import flag_level, t24_band
from assistant.sqlite_eam import SQLiteEAM
from loader import load_data


@dataclass
class FleetContext:
    db_path: Path | None
    drafts: DraftStore
    eam: EAM
    readings: pd.DataFrame
    predictions: dict
    split_by_unit: dict[int, str]
    bands: dict[int, tuple[float, float]]
    drafts_made: list[str] = field(default_factory=list)


def load_context(
    db_path: Path | None,
    data_dir: Path,
    *,
    eam: EAM | None = None,
    draft_path: Path | None = None,
) -> FleetContext:
    """Load a fleet snapshot with readings through each engine's current cycle."""
    if eam is None:
        if db_path is None:
            raise ValueError("A SQLite EAM path is required.")
        eam = SQLiteEAM(db_path)
    if draft_path is None:
        if db_path is None:
            raise ValueError("An assistant database path is required.")
        draft_path = draft_path_for(db_path)
    readings = load_data(data_dir / "train_FD001.txt")
    predictions = load_predictions(data_dir / "predictions_FD001.csv")
    # A unit belongs to one split even when its current-cycle estimate is missing.
    split_by_unit = {
        unit: prediction["split"] for (unit, _), prediction in predictions.items()
    }
    current_cycles = {
        unit_for_asset_id(asset.asset_id): asset.current_cycle
        for asset in eam.list_assets()
    }

    # Each row is compared with its own engine's cutoff before bands are calculated.
    cutoff = readings["unit"].map(current_cycles)
    readings = readings.loc[readings["cycle"] <= cutoff].copy()
    bands = {unit: t24_band(readings, unit) for unit in current_cycles}
    drafts = DraftStore(draft_path)
    return FleetContext(
        db_path, drafts, eam, readings, predictions, split_by_unit, bands
    )


def _unknown_engine(unit):
    return {"error": f"Unknown engine {unit}. Valid engines: 1-100."}


def _rul(ctx, asset: Asset):
    prediction = ctx.predictions.get(
        (unit_for_asset_id(asset.asset_id), asset.current_cycle)
    )
    return None if prediction is None else int(prediction["rul_pred"])


def _recent_readings(ctx, asset: Asset):
    readings = ctx.readings
    at_current_cycle = (readings["unit"] == unit_for_asset_id(asset.asset_id)) & (
        readings["cycle"] <= asset.current_cycle
    )
    recent = readings.loc[at_current_cycle, ["cycle", "s_2"]]
    return recent.sort_values("cycle").tail(10)


def _assess_engine(ctx, asset: Asset, recent):
    band = ctx.bands[unit_for_asset_id(asset.asset_id)]
    return _rul(ctx, asset), flag_level(recent["s_2"].tolist(), *band)


def _engine_status(ctx: FleetContext, asset: Asset, rul: int | None, flag: str) -> dict:
    unit = unit_for_asset_id(asset.asset_id)
    return {
        "unit": unit,
        "rul": rul,
        "flag": flag,
        "current_cycle": asset.current_cycle,
        "split": ctx.split_by_unit.get(unit),
    }


def _report_eam_unavailable(tool):
    @wraps(tool)
    def run(*args, **kwargs):
        try:
            return tool(*args, **kwargs)
        except EAMUnavailable:
            return {"error": EAM_UNAVAILABLE_MESSAGE}

    return run


@_report_eam_unavailable
def fleet_status(ctx: FleetContext, top_n: int = 5) -> list[dict]:
    """Return up to top_n engines ranked by remaining life, then warning severity.

    One cycle equals one day. Missing life estimates are null and rank last.
    """

    def assess(asset: Asset) -> tuple[int | None, str]:
        return _assess_engine(ctx, asset, _recent_readings(ctx, asset))

    ranked = rules.rank_fleet(ctx.eam, assess, top_n)
    return [_engine_status(ctx, asset, rul, flag) for asset, rul, flag in ranked]


@_report_eam_unavailable
def engine_detail(ctx: FleetContext, unit: int) -> dict:
    """Return one engine's life estimate, warning, last ten T24 readings, and open order IDs.

    One cycle equals one day. A null RUL means the estimate is missing.
    """
    asset = ctx.eam.get_asset(asset_id_for_unit(unit))
    if asset is None:
        return _unknown_engine(unit)
    order_ids = rules.open_work_order_ids(ctx.eam, asset)

    recent = _recent_readings(ctx, asset)
    detail = _engine_status(ctx, asset, *_assess_engine(ctx, asset, recent))
    detail["t24_recent"] = [
        {"cycle": int(cycle), "t24": float(t24) if isfinite(t24) else None}
        for cycle, t24 in recent.itertuples(index=False, name=None)
    ]
    detail["open_work_orders"] = order_ids
    return detail


@_report_eam_unavailable
def parts_for(ctx: FleetContext, unit: int) -> list[dict] | dict:
    """Return stock, lead times in days, and whether each part needs ordering.

    One cycle equals one day. A null order decision means the life estimate is missing.
    """
    asset = ctx.eam.get_asset(asset_id_for_unit(unit))
    if asset is None:
        return _unknown_engine(unit)
    results = rules.assess_parts(ctx.eam, _rul(ctx, asset))

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


@_report_eam_unavailable
def work_orders(
    ctx: FleetContext, unit: int, status: str | None = None
) -> list[dict] | dict:
    """Return an engine's work orders, optionally filtered by status, with calendar dates."""
    asset = ctx.eam.get_asset(asset_id_for_unit(unit))
    if asset is None:
        return _unknown_engine(unit)
    orders = ctx.eam.list_work_orders(asset.asset_id, status)

    return [
        {
            "wo_id": order.wo_id,
            "unit": unit,
            "type": order.type,
            "symptom": order.problem_description,
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


@_report_eam_unavailable
def draft_work_order(
    ctx: FleetContext,
    unit: int,
    summary: str,
    reason: str,
    problem_label: str | None = None,
    problem_code: str | None = None,
) -> dict:
    """Save a work order draft for review. Give a short problem label such as seal or bearing."""
    error = rules.draft_error(len(ctx.drafts_made))
    if error is not None:
        return {"error": error}

    asset = ctx.eam.get_asset(asset_id_for_unit(unit))
    if asset is None:
        return _unknown_engine(unit)
    open_orders = ctx.eam.list_work_orders(asset.asset_id, status="open")
    if open_orders:
        return {
            "error": "This engine already has open work. Suggest adding a comment to an existing work order.",
            "open_work_orders": [asdict(order) for order in open_orders],
        }
    code = problem_code.strip() if problem_code else None
    label = " ".join((problem_label or "").casefold().split())
    if not label:
        label = " ".join(summary.casefold().split())
    problem_key = f"code:{code.casefold()}" if code else f"label:{label}"
    order = WorkOrder(
        wo_id="",
        asset_id=asset.asset_id,
        type="corrective",
        status="draft",
        summary=summary,
        comments=reason,
        requested_by="assistant",
        problem_code=code or None,
        site=asset.site,
    )
    evidence = capture_evidence(ctx.eam, ctx.predictions, asset.asset_id)
    draft_id = ctx.drafts.save(
        order, problem_key, {**evidence, "created_by": "assistant"}
    )
    if draft_id not in ctx.drafts_made:
        ctx.drafts_made.append(draft_id)
    return {"draft_id": draft_id}


@_report_eam_unavailable
def draft_part_request(
    ctx: FleetContext, part_id: str, qty: int, reason: str, unit: int | None = None
) -> dict:
    """Save a part request draft for review. Include the engine unit when known."""
    error = rules.draft_error(len(ctx.drafts_made), qty)
    if error is not None:
        return {"error": error}

    asset = ctx.eam.get_asset(asset_id_for_unit(unit)) if unit is not None else None
    if unit is not None and asset is None:
        return _unknown_engine(unit)
    part = next(
        (part for part in ctx.eam.list_parts() if part.part_id == part_id), None
    )
    if part is None:
        return {"error": f"Unknown part {part_id}."}

    request = PartRequest(
        request_id="",
        requested_by="assistant",
        store=part.stock[0].store if part.stock else "main",
        status="draft",
        lines=[PartRequestLine(part_id, qty, part.unit_of_measure)],
        site=asset.site if asset else None,
        asset_id=asset.asset_id if asset else None,
        reason=reason,
    )
    evidence = capture_evidence(ctx.eam, ctx.predictions, request.asset_id, {part_id})
    draft_id = ctx.drafts.save(
        request, part_id, {**evidence, "created_by": "assistant"}
    )
    if draft_id not in ctx.drafts_made:
        ctx.drafts_made.append(draft_id)
    return {"draft_id": draft_id}
