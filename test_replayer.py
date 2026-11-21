from pathlib import Path

import pytest

from loader import load_data
from replayer import EngineReplayer

UNIT = 2


@pytest.fixture(scope="module")
def data():
    data_path = Path(__file__).parent / "data" / "train_FD001.txt"
    return load_data(data_path)


def test_first_next_returns_cycle_one(data):
    row = EngineReplayer(data, UNIT).next()
    assert isinstance(row, dict)
    assert row["cycle"] == 1


def test_second_next_returns_cycle_two(data):
    replayer = EngineReplayer(data, UNIT)
    replayer.next()
    assert replayer.next()["cycle"] == 2


def test_each_row_belongs_to_the_selected_unit(data):
    replayer = EngineReplayer(data, UNIT)
    row_count = (data["unit"] == UNIT).sum()
    for _ in range(row_count):
        assert replayer.next()["unit"] == UNIT


def test_next_returns_none_after_the_last_cycle(data):
    replayer = EngineReplayer(data, UNIT)
    cycles = data.loc[data["unit"] == UNIT, "cycle"]
    for cycle in cycles:
        assert replayer.next()["cycle"] == cycle
    assert replayer.next() is None
