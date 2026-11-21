from pathlib import Path

import pandas as pd
import pytest

from rul.data import add_rul_labels, align_test_rul, load_test, load_train


DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def labeled_train():
    return add_rul_labels(load_train(DATA_DIR / "train_FD001.txt"))


def test_labels_count_down_to_zero(labeled_train):
    engine = labeled_train.loc[labeled_train["unit"] == 1].sort_values("cycle")
    first = engine.iloc[0]
    last = engine.iloc[-1]

    assert last["rul_uncapped"] == 0
    assert first["rul_uncapped"] == last["cycle"] - 1


def test_labels_capped_at_125(labeled_train):
    assert labeled_train["rul_true"].max() == 125
    assert (labeled_train["rul_true"] <= labeled_train["rul_uncapped"]).all()


def test_load_test_shapes():
    rows, labels = load_test(DATA_DIR / "test_FD001.txt", DATA_DIR / "RUL_FD001.txt")

    assert rows.shape == (13_096, 26)
    assert labels.index.tolist() == list(range(1, 101))
    assert sorted(rows["unit"].unique()) == labels.index.tolist()


def test_rul_vector_aligns_by_unit():
    rows = pd.DataFrame({"unit": [1, 1, 2, 2, 3], "cycle": [1, 2, 1, 2, 1]})
    labels = [42, 7, 101]
    shuffled = rows.iloc[[4, 3, 1, 2, 0]]
    expected = {1: 42, 2: 7, 3: 101}

    assert align_test_rul(rows, labels).to_dict() == expected
    assert align_test_rul(shuffled, labels).to_dict() == expected
