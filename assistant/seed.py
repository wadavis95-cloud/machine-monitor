from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from assistant.eam import connect, create_schema, load_predictions
from loader import load_data

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FIRST_DAY = date(2026, 1, 1)


def _seed_machines(conn, data, predictions, rng):
    # Every saved prediction for the same engine belongs to the same split.
    split_by_unit = {
        unit: prediction["split"] for (unit, _), prediction in predictions.items()
    }
    final_cycles = data.groupby("unit", sort=True)["cycle"].max()
    machines = []
    for unit, final_cycle in final_cycles.items():
        current_cycle = round(final_cycle * rng.uniform(0.40, 0.95))
        line = f"Line {(unit - 1) % 4 + 1}"
        area = f"Area {(unit - 1) // 25 + 1}"
        machines.append((unit, line, area, current_cycle, split_by_unit.get(unit)))

    conn.executemany(
        "INSERT INTO machines (unit, line, area, current_cycle, split) VALUES (?, ?, ?, ?, ?)",
        machines,
    )


def _seed_parts(conn):
    conn.executemany(
        """
        INSERT INTO parts (part_id, name, subsystem, on_hand, lead_time_days, unit_cost)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("P-HPC-01", "Compressor seal kit", "HPC", 0, 35, 480),
            ("P-HPC-02", "Compressor vane set", "HPC", 2, 28, 720),
            ("P-HPC-03", "Compressor temperature probe", "HPC", 5, 12, 190),
            ("P-FAN-01", "Fan bearing kit", "Fan", 2, 24, 460),
            ("P-FAN-02", "Fan speed pickup", "Fan", 4, 8, 135),
            ("P-FAN-03", "Fan balance weight set", "Fan", 8, 5, 55),
            ("P-LPT-01", "Turbine seal ring", "LPT", 0, 42, 570),
            ("P-LPT-02", "Turbine temperature probe", "LPT", 3, 16, 215),
            ("P-LPT-03", "Turbine fastener set", "LPT", 6, 9, 65),
            ("P-OIL-01", "Oil filter element", "Lubrication", 10, 6, 40),
            ("P-OIL-02", "Oil pressure sender", "Lubrication", 3, 11, 120),
            ("P-OIL-03", "Oil line seal set", "Lubrication", 7, 7, 45),
        ],
    )


def _seed_work_orders(conn):
    examples = [
        (
            "corrective",
            "T24 trending high",
            "Reseated the probe connector",
            None,
            "AK",
            "T24 returned to its normal range on the next run.",
            "closed",
        ),
        (
            "pm",
            "Scheduled oil service",
            "Replaced the filter and checked pressure",
            "P-OIL-01",
            "LM",
            "Oil pressure stayed steady during the test run.",
            "closed",
        ),
        (
            "corrective",
            "Fan speed fluctuates",
            None,
            None,
            "RJ",
            "Check the speed pickup during the next service window.",
            "open",
        ),
    ]
    machines = conn.execute("SELECT unit, current_cycle FROM machines ORDER BY unit")
    orders = []
    for number, (unit, current_cycle) in enumerate(machines):
        kind, symptom, action, parts, tech, comments, status = examples[
            number % len(examples)
        ]
        opened = _cycle_date(max(0, current_cycle - 8))
        closed = _cycle_date(max(0, current_cycle - 6)) if status == "closed" else None
        orders.append(
            (
                f"WO-{1001 + number}",
                unit,
                kind,
                symptom,
                action,
                parts,
                tech,
                comments,
                opened,
                closed,
                status,
            )
        )

    conn.executemany(
        """
        INSERT INTO work_orders
            (wo_id, unit, type, symptom, action, parts_used, tech, comments, opened, closed, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        orders,
    )


def _cycle_date(cycle):
    return (FIRST_DAY + timedelta(days=cycle)).isoformat()


def build_eam(
    db_path: Path, data: pd.DataFrame, predictions: dict, seed: int = 0
) -> None:
    """Build a fresh demo database and replace the previous file when it is ready."""
    rng = np.random.default_rng(seed)
    # Build beside the target so a failed seed leaves the previous database intact.
    with TemporaryDirectory(dir=db_path.parent) as directory:
        fresh_path = Path(directory) / db_path.name
        with closing(connect(fresh_path)) as conn:
            create_schema(conn)
            _seed_machines(conn, data, predictions, rng)
            _seed_parts(conn)
            _seed_work_orders(conn)
            conn.commit()
        fresh_path.replace(db_path)


if __name__ == "__main__":
    data = load_data(DATA_DIR / "train_FD001.txt")
    predictions = load_predictions(DATA_DIR / "predictions_FD001.csv")
    build_eam(DATA_DIR / "eam.sqlite", data, predictions)
