"""Maintenance data and operations shared by the assistant and its EAM adapters."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class PartQuantity:
    part_id: str
    qty: int


@dataclass
class StoreStock:
    store: str
    on_hand: int
    reorder_point: int | None = None


@dataclass
class PartRequestLine:
    part_id: str
    qty: int
    unit: str


@dataclass
class Asset:
    asset_id: str
    name: str
    location: str
    current_cycle: int
    department: str | None = None
    status: str | None = None
    parts: list[PartQuantity] = field(default_factory=list)
    site: str | None = None


@dataclass
class WorkOrder:
    wo_id: str
    asset_id: str
    type: str
    status: str
    summary: str | None = None
    comments: str | None = None
    priority: str | None = None
    location: str | None = None
    department: str | None = None
    requested_by: str | None = None
    assigned_to: str | None = None
    people: list[str] = field(default_factory=list)
    parts: list[PartQuantity] = field(default_factory=list)
    opened: str | None = None
    closed: str | None = None
    problem_code: str | None = None
    cause_code: str | None = None
    action_code: str | None = None
    site: str | None = None
    problem_description: str | None = None


@dataclass
class Part:
    part_id: str
    name: str
    unit_of_measure: str
    lead_time_days: int
    unit_cost: float
    stock: list[StoreStock] = field(default_factory=list)


@dataclass
class PartRequest:
    request_id: str
    requested_by: str
    store: str
    status: str
    wo_id: str | None = None
    need_by: str | None = None
    lines: list[PartRequestLine] = field(default_factory=list)
    site: str | None = None


class EAM(Protocol):
    def list_assets(self) -> Sequence[Asset]: ...

    def get_asset(self, asset_id: str) -> Asset | None: ...

    def list_parts(self) -> Sequence[Part]: ...

    def list_work_orders(
        self, asset_id: str, status: str | None = None
    ) -> Sequence[WorkOrder]: ...

    def find_by_reference(self, ref: str) -> str | None: ...

    def submit_work_request(self, order: WorkOrder, ref: str) -> str: ...

    def submit_part_request(self, request: PartRequest, ref: str) -> str: ...
