"""Translate the mock Hexagon HTTP API to and from the generic EAM contract."""

from urllib.parse import quote

import httpx

from assistant.eam_contract import (
    Asset,
    EAMUnavailable,
    Part,
    PartQuantity,
    PartRequest,
    StoreStock,
    WorkOrder,
)

TIMEOUT_SECONDS = 3
ORDER_TYPES = {"REPAIR": "corrective", "PREVENTIVE": "pm"}
ORDER_CODES = {kind: code for code, kind in ORDER_TYPES.items()}
WORK_STATUSES = {"OPEN": "open", "REQUESTED": "open", "CLOSED": "closed"}


class HexagonEAM:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.transport = transport

    def _request(
        self, method: str, path: str, *, ref: str | None = None, **kwargs
    ) -> httpx.Response:
        headers = {"X-API-Key": self.api_key}
        if ref is not None:
            headers["Idempotency-Key"] = ref
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=TIMEOUT_SECONDS,
                headers=headers,
                transport=self.transport,
                trust_env=False,
            ) as client:
                response = client.request(method, path, **kwargs)
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ) as error:
            raise EAMUnavailable("Hexagon connection failed.") from error
        if response.is_server_error:
            raise EAMUnavailable(f"Hexagon returned HTTP {response.status_code}.")
        return response

    def list_assets(self) -> list[Asset]:
        rows = self._request("GET", "/assets").raise_for_status().json()
        return [_asset(row) for row in rows]

    def get_asset(self, asset_id: str) -> Asset | None:
        response = self._request("GET", f"/assets/{quote(asset_id, safe='')}")
        if response.status_code == 404:
            return None
        return _asset(response.raise_for_status().json())

    def list_parts(self) -> list[Part]:
        rows = self._request("GET", "/parts").raise_for_status().json()
        return [
            Part(
                part_id=row["ID"],
                name=row["NAME"],
                unit_of_measure=row["UOM"],
                lead_time_days=row["LEAD_DAYS"],
                unit_cost=row["UNIT_COST"],
                stock=[
                    StoreStock(stock["STORE"], stock["ON_HAND"], stock["REORDER_POINT"])
                    for stock in row["STOCK"]
                ],
            )
            for row in rows
        ]

    def list_work_orders(
        self, asset_id: str, status: str | None = None
    ) -> list[WorkOrder]:
        params = {"asset": asset_id}
        if status is not None:
            params["status"] = status
        rows = (
            self._request("GET", "/workorders", params=params).raise_for_status().json()
        )
        return [_work_order(row) for row in rows]

    def find_by_reference(self, ref: str) -> str | None:
        rows = (
            self._request("GET", "/references", params={"reference": ref})
            .raise_for_status()
            .json()
        )
        return rows[0]["ID"] if rows else None

    def submit_work_request(self, order: WorkOrder, ref: str) -> str:
        body = {
            "REFERENCE": ref,
            "ASSET": {"ID": order.asset_id},
            "ORDER_TYPE": {"CODE": ORDER_CODES[order.type]},
            "SUMMARY": order.summary,
            "COMMENTS": order.comments,
            "PROBLEM_DESCRIPTION": order.problem_description,
            "LOCATION": order.location,
            "DEPARTMENT": order.department,
            "PRIORITY": _code_object(order.priority),
            "REQUESTED_BY": order.requested_by,
            "PARTS": [
                {"PART": {"ID": part.part_id}, "QUANTITY": part.qty}
                for part in order.parts
            ],
            "PROBLEM": _code_object(order.problem_code),
            "CAUSE": _code_object(order.cause_code),
            "REMEDY": _code_object(order.action_code),
            "SITE": order.site,
        }
        response = self._request("POST", "/workrequests", ref=ref, json=body)
        return response.raise_for_status().json()["ID"]

    def submit_part_request(self, request: PartRequest, ref: str) -> str:
        body = {
            "REFERENCE": ref,
            "ASSET": {"ID": request.asset_id} if request.asset_id is not None else None,
            "WORK_ORDER": {"ID": request.wo_id} if request.wo_id is not None else None,
            "STORE": request.store,
            "LINES": [
                {"PART": {"ID": line.part_id}, "QUANTITY": line.qty, "UOM": line.unit}
                for line in request.lines
            ],
            "REQUESTED_BY": request.requested_by,
            "NEED_BY": request.need_by,
            "REASON": request.reason,
            "SITE": request.site,
        }
        response = self._request("POST", "/partrequisitions", ref=ref, json=body)
        return response.raise_for_status().json()["ID"]


def _code_value(value: dict | None) -> str | None:
    return None if value is None else value["CODE"]


def _code_object(value: str | None) -> dict | None:
    return None if value is None else {"CODE": value}


def _parts(rows: list[dict]) -> list[PartQuantity]:
    return [PartQuantity(row["PART"]["ID"], row["QUANTITY"]) for row in rows]


def _asset(row: dict) -> Asset:
    status = _code_value(row["STATUS"])
    return Asset(
        asset_id=row["ID"],
        name=row["NAME"],
        location=row["LOCATION"],
        current_cycle=row["CURRENT_CYCLE"],
        department=row["DEPARTMENT"],
        status=None if status is None else status.lower(),
        parts=_parts(row["PARTS"]),
        site=row["SITE"],
    )


def _work_order(row: dict) -> WorkOrder:
    priority = _code_value(row["PRIORITY"])
    return WorkOrder(
        wo_id=row["ID"],
        asset_id=row["ASSET"]["ID"],
        type=ORDER_TYPES[row["ORDER_TYPE"]["CODE"]],
        status=WORK_STATUSES[row["STATUS"]["CODE"]],
        summary=row["SUMMARY"],
        comments=row["COMMENTS"],
        priority=None if priority is None else priority.lower(),
        location=row["LOCATION"],
        department=row["DEPARTMENT"],
        requested_by=row["REQUESTED_BY"],
        assigned_to=row["ASSIGNED_TO"],
        people=row["PEOPLE"],
        parts=_parts(row["PARTS"]),
        opened=row["OPENED"],
        closed=row["CLOSED"],
        problem_code=_code_value(row["PROBLEM"]),
        cause_code=_code_value(row["CAUSE"]),
        action_code=_code_value(row["REMEDY"]),
        site=row["SITE"],
        problem_description=row["PROBLEM_DESCRIPTION"],
    )
