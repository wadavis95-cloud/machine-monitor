"""Map the demo SQLite database to the shared maintenance contract."""

from contextlib import closing
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
            SELECT wo_id, type, status, action, comments, tech, parts_used,
                   opened, closed, symptom
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
                parts=[]
                if row["parts_used"] is None
                else [PartQuantity(row["parts_used"], 1)],
                opened=row["opened"],
                closed=row["closed"],
                problem_description=row["symptom"],
            )
            for row in rows
        ]

    # Sending and reference lookup are introduced after the draft lifecycle is split.
    def find_by_reference(self, ref: str) -> str | None:
        raise NotImplementedError

    def submit_work_request(self, order: WorkOrder, ref: str) -> str:
        raise NotImplementedError

    def submit_part_request(self, request: PartRequest, ref: str) -> str:
        raise NotImplementedError
