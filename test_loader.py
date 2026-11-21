from pathlib import Path

import pytest

from loader import load_data


@pytest.fixture(scope="module")
def data():
    data_path = Path(__file__).parent / "data" / "train_FD001.txt"
    return load_data(data_path)


def test_column_names(data):
    expected = ["unit", "cycle", "op_1", "op_2", "op_3"]
    expected += [f"s_{number}" for number in range(1, 22)]
    assert data.columns.tolist() == expected


def test_no_missing_values(data):
    assert not data.isna().any().any()


def test_row_count(data):
    assert len(data) == 20_631


def test_unique_unit_count(data):
    assert data["unit"].nunique() == 100
