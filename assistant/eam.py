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
