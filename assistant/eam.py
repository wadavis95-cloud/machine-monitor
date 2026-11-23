import sqlite3
from pathlib import Path

import pandas as pd


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE machines (
            unit INTEGER PRIMARY KEY,
            line TEXT NOT NULL,
            area TEXT NOT NULL,
            current_cycle INTEGER NOT NULL,
            split TEXT
        );
        CREATE TABLE parts (
            part_id TEXT PRIMARY KEY NOT NULL,
            name TEXT NOT NULL,
            subsystem TEXT NOT NULL,
            on_hand INTEGER NOT NULL,
            lead_time_days INTEGER NOT NULL,
            unit_cost REAL NOT NULL
        );
        CREATE TABLE work_orders (
            wo_id TEXT PRIMARY KEY NOT NULL,
            unit INTEGER NOT NULL REFERENCES machines(unit),
            type TEXT NOT NULL CHECK (type IN ('corrective', 'pm')),
            symptom TEXT,
            action TEXT,
            parts_used TEXT,
            tech TEXT,
            comments TEXT,
            opened TEXT,
            closed TEXT,
            status TEXT NOT NULL CHECK (status IN ('closed', 'open', 'draft', 'rejected'))
        );
        CREATE TABLE part_requests (
            pr_id TEXT PRIMARY KEY NOT NULL,
            part_id TEXT NOT NULL REFERENCES parts(part_id),
            qty INTEGER NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('draft', 'submitted', 'rejected')),
            created_by TEXT NOT NULL
        );
        """)


def list_drafts(conn: sqlite3.Connection) -> list[dict]:
    """Return the work orders and part requests still awaiting review."""
    orders = conn.execute("""
        SELECT wo_id AS id, 'work_order' AS kind, unit, action AS summary
        FROM work_orders WHERE status = 'draft' ORDER BY wo_id
        """)
    requests = conn.execute("""
        SELECT pr_id AS id, 'part_request' AS kind, part_id, reason, qty
        FROM part_requests WHERE status = 'draft' ORDER BY pr_id
        """)
    return [dict(row) for row in orders] + [dict(row) for row in requests]


def decide_draft(conn: sqlite3.Connection, draft_id: str, approve: bool) -> str:
    """Approve or reject a draft and return its saved status."""
    if draft_id.startswith("WO-"):
        table, id_column, approved_status = "work_orders", "wo_id", "open"
    elif draft_id.startswith("PR-"):
        table, id_column, approved_status = "part_requests", "pr_id", "submitted"
    else:
        raise KeyError(draft_id)

    status = approved_status if approve else "rejected"
    with conn:
        # Check and change the status together so only one decision can win.
        # The table and column names come from the fixed choices above.
        updated = conn.execute(
            f"UPDATE {table} SET status = ? WHERE {id_column} = ? AND status = 'draft'",
            (status, draft_id),
        )
        if updated.rowcount == 0:
            existing = conn.execute(
                f"SELECT 1 FROM {table} WHERE {id_column} = ?", (draft_id,)
            ).fetchone()
            if existing is None:
                raise KeyError(draft_id)
            raise ValueError(f"{draft_id} is no longer a draft.")
    return status


def load_predictions(path: Path | None):
    """Read saved estimates into a lookup by engine and cycle."""
    if path is None:
        return {}
    try:
        rows = pd.read_csv(
            path, comment="#", usecols=["unit", "cycle", "split", "rul_trees"]
        )
    except FileNotFoundError, pd.errors.EmptyDataError:
        return {}
    if rows.duplicated(["unit", "cycle"]).any():
        raise ValueError("Duplicate prediction rows for the same unit and cycle.")

    # Unreadable values become missing. The export contains whole-cycle estimates.
    rows["rul_trees"] = pd.to_numeric(rows["rul_trees"], errors="coerce")
    predictions = {}
    for row in rows.loc[rows["split"].isin(["train", "val"])].itertuples(index=False):
        estimate = row.rul_trees
        if pd.notna(estimate) and float(estimate).is_integer():
            predictions[row.unit, row.cycle] = {
                "rul_pred": int(estimate),
                "split": row.split,
            }
    return predictions
