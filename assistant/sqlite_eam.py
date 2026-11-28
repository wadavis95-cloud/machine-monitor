"""Map the demo SQLite database to the shared maintenance contract."""

import json
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Row

from assistant.asset_ids import asset_id_for_unit, unit_for_asset_id
from assistant.eam import connect
from assistant.eam_contract import (
    Asset,
    Part,
    PartQuantity,
    PartRequest,
    StoreStock,
    WorkOrder,
)


class SQLiteEAM:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    @staticmethod
    def _asset(row: Row) -> Asset:
        return Asset(
            asset_id=asset_id_for_unit(row["unit"]),
            name=f"Engine {row['unit']}",
            location=row["line"],
            current_cycle=row["current_cycle"],
        )

    def list_assets(self) -> list[Asset]:
        with closing(connect(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT unit, line, current_cycle FROM machines ORDER BY unit"
            )
            return [self._asset(row) for row in rows]

    def get_asset(self, asset_id: str) -> Asset | None:
        try:
            unit = unit_for_asset_id(asset_id)
        except ValueError:
            return None
        with closing(connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT unit, line, current_cycle FROM machines WHERE unit = ?",
                (unit,),
            ).fetchone()
        return None if row is None else self._asset(row)

    def list_parts(self) -> list[Part]:
        with closing(connect(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT part_id, name, on_hand, lead_time_days, unit_cost FROM parts ORDER BY part_id"
            ).fetchall()
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
    ) -> list[WorkOrder]:
        try:
            unit = unit_for_asset_id(asset_id)
        except ValueError:
            return []
        query = """
            SELECT wo_id, type, status, action, comments, tech, parts_used, parts_json,
                   opened, closed, symptom, problem_code
            FROM work_orders WHERE unit = ?
        """
        params = (unit,)
        if status is not None:
            query += " AND status = ?"
            params += (status,)
        with closing(connect(self.db_path)) as conn:
            rows = conn.execute(query + " ORDER BY wo_id", params).fetchall()
        return [
            WorkOrder(
                wo_id=row["wo_id"],
                asset_id=asset_id,
                type=row["type"],
                status=row["status"],
                summary=row["action"],
                comments=row["comments"],
                assigned_to=row["tech"],
                parts=_work_order_parts(row),
                problem_code=row["problem_code"],
                opened=row["opened"],
                closed=row["closed"],
                problem_description=row["symptom"],
            )
            for row in rows
        ]

    def find_by_reference(self, ref: str) -> str | None:
        with closing(connect(self.db_path, timeout=3)) as conn:
            row = conn.execute(
                """SELECT wo_id FROM work_orders WHERE reference = ?
                   UNION ALL SELECT pr_id FROM part_requests WHERE reference = ?""",
                (ref, ref),
            ).fetchone()
        return None if row is None else row[0]

    def submit_work_request(self, order: WorkOrder, ref: str) -> str:
        unit = unit_for_asset_id(order.asset_id)
        with closing(connect(self.db_path, timeout=3)) as conn, conn:
            conn.execute(
                """INSERT INTO work_orders
                   (wo_id, unit, type, symptom, action, parts_json, tech, comments, opened,
                    status, problem_code, reference)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                   ON CONFLICT(reference) DO NOTHING""",
                (
                    order.wo_id,
                    unit,
                    order.type,
                    order.problem_description,
                    order.summary,
                    json.dumps([asdict(part) for part in order.parts]),
                    order.assigned_to,
                    order.comments,
                    order.opened or datetime.now(UTC).date().isoformat(),
                    order.problem_code,
                    ref,
                ),
            )
            return conn.execute(
                "SELECT wo_id FROM work_orders WHERE reference = ?", (ref,)
            ).fetchone()[0]

    def submit_part_request(self, request: PartRequest, ref: str) -> str:
        if not request.lines:
            raise ValueError("A part request needs at least one line.")
        unit = (
            unit_for_asset_id(request.asset_id)
            if request.asset_id is not None
            else None
        )
        with closing(connect(self.db_path, timeout=3)) as conn, conn:
            inserted = conn.execute(
                """INSERT INTO part_requests
                   (pr_id, unit, wo_id, store, need_by, reason, status, created_by, reference)
                   VALUES (?, ?, ?, ?, ?, ?, 'submitted', ?, ?)
                   ON CONFLICT(reference) DO NOTHING""",
                (
                    request.request_id,
                    unit,
                    request.wo_id,
                    request.store,
                    request.need_by,
                    request.reason,
                    request.requested_by,
                    ref,
                ),
            ).rowcount
            if inserted:
                conn.executemany(
                    """INSERT INTO part_request_lines (pr_id, line_no, part_id, qty, unit)
                       VALUES (?, ?, ?, ?, ?)""",
                    [
                        (request.request_id, number, line.part_id, line.qty, line.unit)
                        for number, line in enumerate(request.lines, start=1)
                    ],
                )
            return conn.execute(
                "SELECT pr_id FROM part_requests WHERE reference = ?", (ref,)
            ).fetchone()[0]


def _work_order_parts(row: Row) -> list[PartQuantity]:
    if row["parts_json"] is not None:
        return [PartQuantity(**part) for part in json.loads(row["parts_json"])]
    return [] if row["parts_used"] is None else [PartQuantity(row["parts_used"], 1)]
