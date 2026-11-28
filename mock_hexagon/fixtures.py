"""Generate the mock's JSON fixtures from a fresh copy of the demo seed."""

from pathlib import Path
from tempfile import TemporaryDirectory

from assistant.eam import load_predictions
from assistant.eam_contract import Asset, Part, WorkOrder
from assistant.seed import DATA_DIR, build_eam
from assistant.sqlite_eam import SQLiteEAM
from loader import load_data

ORDER_TYPES = {"corrective": "REPAIR", "pm": "PREVENTIVE"}
COMMENT_EDITS = (
    ("returned to its normal range on the next run", "back in norm rng on nxt run"),
    ("stayed steady during the test run", "held steady during tst run"),
    (
        "Check the speed pickup during the next service window",
        "Chk speed pikup at nxt svc window",
    ),
)


def code(value: str | None) -> dict | None:
    return None if value is None else {"CODE": value}


def _notes(comments: str | None) -> str | None:
    if comments is None:
        return None
    for original, shorthand in COMMENT_EDITS:
        comments = comments.replace(original, shorthand)
    return comments


def _asset_record(asset: Asset) -> dict:
    return {
        "ID": asset.asset_id,
        "NAME": asset.name,
        "LOCATION": asset.location,
        "DEPARTMENT": asset.department,
        "STATUS": code(asset.status),
        "CURRENT_CYCLE": asset.current_cycle,
        "PARTS": [
            {"PART": {"ID": part.part_id}, "QUANTITY": part.qty} for part in asset.parts
        ],
        "SITE": asset.site,
    }


def _part_record(part: Part) -> dict:
    return {
        "ID": part.part_id,
        "NAME": part.name,
        "UOM": part.unit_of_measure,
        "LEAD_DAYS": part.lead_time_days,
        "UNIT_COST": part.unit_cost,
        "STOCK": [
            {
                "STORE": stock.store,
                "ON_HAND": stock.on_hand,
                "REORDER_POINT": stock.reorder_point,
            }
            for stock in part.stock
        ],
    }


def _order_record(order: WorkOrder) -> dict:
    return {
        "ID": order.wo_id,
        "ASSET": {"ID": order.asset_id},
        "ORDER_TYPE": code(ORDER_TYPES[order.type]),
        "STATUS": code(order.status.upper()),
        "SUMMARY": order.summary,
        "COMMENTS": _notes(order.comments),
        "PROBLEM_DESCRIPTION": order.problem_description,
        "LOCATION": order.location,
        "DEPARTMENT": order.department,
        "PRIORITY": code(order.priority),
        "REQUESTED_BY": order.requested_by,
        "ASSIGNED_TO": order.assigned_to,
        "PEOPLE": order.people,
        "PARTS": [
            {"PART": {"ID": part.part_id}, "QUANTITY": part.qty} for part in order.parts
        ],
        "OPENED": order.opened,
        "CLOSED": order.closed,
        "PROBLEM": code(order.problem_code),
        "CAUSE": code(order.cause_code),
        "REMEDY": code(order.action_code),
        "SITE": order.site,
        "REFERENCE": None,
    }


def seed_fixtures(data_dir: Path = DATA_DIR) -> tuple[dict, dict, dict]:
    readings = load_data(data_dir / "train_FD001.txt")
    predictions = load_predictions(data_dir / "predictions_FD001.csv")
    with TemporaryDirectory() as directory:
        path = Path(directory) / "eam.sqlite"
        build_eam(path, readings, predictions, seed=0)
        eam = SQLiteEAM(path)
        assets = {asset.asset_id: _asset_record(asset) for asset in eam.list_assets()}
        parts = {part.part_id: _part_record(part) for part in eam.list_parts()}
        orders = {
            order.wo_id: _order_record(order)
            for asset_id in assets
            for order in eam.list_work_orders(asset_id)
        }
    return assets, parts, orders
