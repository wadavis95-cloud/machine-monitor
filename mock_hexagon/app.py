"""A standalone, in-memory mock EAM REST service."""

import os
from datetime import UTC, datetime
from hmac import compare_digest
from itertools import count
from threading import Lock
from time import sleep

from flask import Flask, jsonify, request

from mock_hexagon.fixtures import ORDER_TYPES, code, seed_fixtures

SLOW_SECONDS = 4
MODES = {"normal", "down", "slow", "lost-reply"}


def create_app(
    *,
    api_key: str | None = None,
    mode: str | None = None,
    ignore_idempotency: bool | None = None,
) -> Flask:
    app = Flask(__name__, static_folder=None)
    if api_key is None:
        api_key = os.environ.get("MOCK_HEXAGON_API_KEY", "demo-key")
    if not api_key:
        raise ValueError("The mock API key must not be empty.")
    if mode is None:
        mode = os.environ.get("MOCK_HEXAGON_MODE", "normal")
    if mode not in MODES:
        raise ValueError(f"Unknown mock mode: {mode!r}")
    if ignore_idempotency is None:
        ignore_idempotency = os.environ.get("MOCK_HEXAGON_IGNORE_IDEMPOTENCY") == "1"

    assets, parts, work_orders = seed_fixtures()
    requisitions = {}
    sequences = {"WR": count(1), "PR": count(1)}
    idempotent_records = {}
    lock = Lock()

    @app.before_request
    def authenticate_and_simulate():
        supplied = request.headers.get("X-API-Key", "")
        if not compare_digest(supplied.encode(), api_key.encode()):
            return jsonify(ERROR="Missing or invalid API key."), 401
        if mode == "down":
            return jsonify(ERROR="Mock EAM is unavailable."), 503
        if mode == "slow":
            sleep(SLOW_SECONDS)
        return None

    @app.get("/assets")
    def list_assets():
        return jsonify(list(assets.values()))

    @app.get("/assets/<asset_id>")
    def get_asset(asset_id):
        record = assets.get(asset_id)
        if record is None:
            return jsonify(ERROR="Asset not found."), 404
        return jsonify(record)

    @app.get("/parts")
    def list_parts():
        return jsonify(list(parts.values()))

    @app.get("/workorders")
    def list_work_orders():
        asset_id = request.args.get("asset")
        status = request.args.get("status")
        statuses = _status_codes(status) if status is not None else None
        with lock:
            orders = [
                item
                for item in work_orders.values()
                if (asset_id is None or item["ASSET"]["ID"] == asset_id)
                and (statuses is None or item["STATUS"]["CODE"] in statuses)
            ]
        return jsonify(orders)

    @app.get("/workorders/<order_id>")
    def get_work_order(order_id):
        with lock:
            record = work_orders.get(order_id)
        if record is None:
            return jsonify(ERROR="Work order not found."), 404
        return jsonify(record)

    @app.get("/references")
    def find_by_reference():
        ref = request.args.get("reference")
        if not ref or not ref.strip():
            return jsonify(ERROR="The reference query parameter is required."), 400
        with lock:
            matches = [
                {"ID": record["ID"], "REFERENCE": ref, "KIND": kind}
                for kind, records in (
                    ("WORK_REQUEST", work_orders),
                    ("PART_REQUISITION", requisitions),
                )
                for record in records.values()
                if record["REFERENCE"] == ref
            ]
        return jsonify(matches)

    def create_record(prefix, records, validate):
        key = request.headers.get("Idempotency-Key")
        use_key = bool(key) and not ignore_idempotency
        body = request.get_json(silent=True)
        with lock:
            if use_key and (prefix, key) in idempotent_records:
                return jsonify(records[idempotent_records[prefix, key]]), 200
            if not isinstance(body, dict):
                return jsonify(ERROR="Expected a JSON object."), 400
            if not _nonempty(body.get("REFERENCE")):
                return jsonify(ERROR="REFERENCE is required."), 400
            try:
                record = validate(body)
            except ValueError as error:
                return jsonify(ERROR=str(error)), 400

            record_id = f"{prefix}-{next(sequences[prefix]):04d}"
            record.update(ID=record_id, REFERENCE=body["REFERENCE"])
            records[record_id] = record
            if use_key:
                idempotent_records[prefix, key] = record_id

        if mode == "lost-reply":
            return jsonify(
                ERROR="Mock lost the response after creating the record."
            ), 502
        return jsonify(record), 201

    def work_request(body):
        asset_id = _known_asset(body, assets, required=True)
        if not _nonempty(body.get("SUMMARY")):
            raise ValueError("SUMMARY is required.")
        order_type = body.get("ORDER_TYPE", code("REPAIR"))
        if (
            not isinstance(order_type, dict)
            or order_type.get("CODE") not in ORDER_TYPES.values()
        ):
            raise ValueError("ORDER_TYPE must contain a supported CODE.")
        return {
            "ASSET": {"ID": asset_id},
            "ORDER_TYPE": order_type,
            "STATUS": code("REQUESTED"),
            "SUMMARY": body["SUMMARY"],
            "COMMENTS": body.get("COMMENTS"),
            "PROBLEM_DESCRIPTION": body.get("PROBLEM_DESCRIPTION"),
            "LOCATION": body.get("LOCATION"),
            "DEPARTMENT": body.get("DEPARTMENT"),
            "PRIORITY": body.get("PRIORITY"),
            "REQUESTED_BY": body.get("REQUESTED_BY"),
            "ASSIGNED_TO": None,
            "PEOPLE": [],
            "PARTS": body.get("PARTS", []),
            "OPENED": datetime.now(UTC).date().isoformat(),
            "CLOSED": None,
            "PROBLEM": body.get("PROBLEM"),
            "CAUSE": body.get("CAUSE"),
            "REMEDY": body.get("REMEDY"),
            "SITE": body.get("SITE"),
        }

    def part_requisition(body):
        asset_id = _known_asset(body, assets)
        if not _nonempty(body.get("STORE")):
            raise ValueError("STORE is required.")
        lines = body.get("LINES")
        if not isinstance(lines, list) or not lines:
            raise ValueError("LINES must contain at least one part.")
        return {
            "ASSET": None if asset_id is None else {"ID": asset_id},
            "WORK_ORDER": body.get("WORK_ORDER"),
            "STATUS": code("SUBMITTED"),
            "STORE": body["STORE"],
            "LINES": [_requisition_line(line, parts) for line in lines],
            "REQUESTED_BY": body.get("REQUESTED_BY"),
            "NEED_BY": body.get("NEED_BY"),
            "REASON": body.get("REASON"),
            "SITE": body.get("SITE"),
        }

    @app.post("/workrequests")
    def submit_work_request():
        return create_record("WR", work_orders, work_request)

    @app.post("/partrequisitions")
    def submit_part_requisition():
        return create_record("PR", requisitions, part_requisition)

    return app


def _status_codes(status: str) -> set[str]:
    code_value = status.upper()
    if code_value == "OPEN":
        return {"OPEN", "REQUESTED"}
    return {code_value}


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _known_asset(body, assets, *, required=False) -> str | None:
    asset = body.get("ASSET")
    if asset is None and not required:
        return None
    asset_id = asset.get("ID") if isinstance(asset, dict) else None
    if not isinstance(asset_id, str) or asset_id not in assets:
        raise ValueError("ASSET must identify a known asset.")
    return asset_id


def _requisition_line(line, parts) -> dict:
    part = line.get("PART") if isinstance(line, dict) else None
    part_id = part.get("ID") if isinstance(part, dict) else None
    if not isinstance(part_id, str) or part_id not in parts:
        raise ValueError("Each line must identify a known PART.")
    qty = line.get("QUANTITY")
    if type(qty) is not int or qty < 1:
        raise ValueError("QUANTITY must be a positive integer.")
    uom = line.get("UOM", parts[part_id]["UOM"])
    if not _nonempty(uom):
        raise ValueError("UOM must be a nonempty string.")
    return {"PART": {"ID": part_id}, "QUANTITY": qty, "UOM": uom}
