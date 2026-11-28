"""Capture and compare the EAM and prediction facts in a draft."""

from assistant.asset_ids import unit_for_asset_id
from assistant.eam_contract import EAM


def capture_evidence(
    eam: EAM, predictions: dict, asset_id: str | None, part_ids: set[str] | None = None
) -> dict:
    asset = eam.get_asset(asset_id) if asset_id is not None else None
    prediction = (
        predictions.get((unit_for_asset_id(asset.asset_id), asset.current_cycle))
        if asset is not None
        else None
    )
    if part_ids is None:
        part_ids = (
            {part.part_id for part in asset.parts} if asset is not None else set()
        )
    stock = {
        part.part_id: {store.store: store.on_hand for store in part.stock}
        for part in (eam.list_parts() if part_ids else ())
        if part.part_id in part_ids
    }
    orders = {
        order.wo_id: {"status": order.status, "comments": order.comments}
        for order in (eam.list_work_orders(asset.asset_id) if asset is not None else ())
    }
    return {
        "rul": None if prediction is None else int(prediction["rul_pred"]),
        "stock": stock,
        "work_orders": orders,
    }


def recheck_evidence(draft: dict, eam: EAM, predictions: dict) -> dict:
    payload = draft["payload"]
    part_ids = (
        {line["part_id"] for line in payload["lines"]}
        if draft["kind"] == "part_request"
        else None
    )
    current = capture_evidence(eam, predictions, payload["asset_id"], part_ids)
    return {
        field: {"stored": draft["evidence"][field], "current": value}
        for field, value in current.items()
        if value != draft["evidence"][field]
    }
