from contextlib import closing
from pathlib import Path

import pytest

from assistant import eam, seed
from loader import load_data

DATA_DIR = Path(__file__).with_name("data")


@pytest.fixture(scope="module")
def seed_inputs():
    data = load_data(DATA_DIR / "train_FD001.txt")
    predictions = eam.load_predictions(DATA_DIR / "predictions_FD001.csv")
    return data, predictions


@pytest.fixture
def eam_conn(tmp_path, seed_inputs):
    db_path = tmp_path / "eam.sqlite"
    seed.build_eam(db_path, *seed_inputs, seed=0)
    with closing(eam.connect(db_path)) as conn:
        yield conn


def test_seed_is_deterministic(eam_conn, tmp_path, seed_inputs):
    second_path = tmp_path / "second.sqlite"
    seed.build_eam(second_path, *seed_inputs, seed=0)

    with closing(eam.connect(second_path)) as second_conn:
        assert list(eam_conn.iterdump()) == list(second_conn.iterdump())


def test_machines_one_row_per_engine(eam_conn, seed_inputs):
    data, _ = seed_inputs
    final_cycles = data.groupby("unit")["cycle"].max()
    machines = eam_conn.execute(
        "SELECT unit, current_cycle FROM machines ORDER BY unit"
    ).fetchall()

    assert len(machines) == 100
    assert [unit for unit, _ in machines] == sorted(final_cycles.index)
    for unit, current_cycle in machines:
        final_cycle = final_cycles[unit]
        # Allow one whole cycle at each end for rounding.
        assert 0.40 * final_cycle - 1 <= current_cycle <= 0.95 * final_cycle + 1


def test_no_hindsight_columns(eam_conn):
    forbidden = {"rul_true", "final_cycle", "rul"}
    tables = eam_conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
    for (table,) in tables:
        columns = eam_conn.execute("SELECT name FROM pragma_table_info(?)", (table,))
        assert forbidden.isdisjoint(name.lower() for (name,) in columns), table


def test_demo_has_an_order_now_case(eam_conn, seed_inputs):
    _, predictions = seed_inputs
    out_of_stock = eam_conn.execute(
        "SELECT lead_time_days FROM parts WHERE on_hand = 0"
    ).fetchall()
    machines = eam_conn.execute("SELECT unit, current_cycle FROM machines")

    # Look up the prediction at the exact cycle stored for each engine.
    current_ruls = [
        predictions[unit, cycle]["rul_pred"]
        for unit, cycle in machines
        if (unit, cycle) in predictions
    ]

    assert out_of_stock
    assert any(rul <= days + 10 for (days,) in out_of_stock for rul in current_ruls)


def test_work_order_comments_nonempty(eam_conn):
    orders = eam_conn.execute(
        "SELECT wo_id, comments FROM work_orders "
        "WHERE type = 'corrective' AND status = 'closed'"
    ).fetchall()
    assert orders
    for wo_id, comments in orders:
        assert comments and comments.strip(), wo_id
