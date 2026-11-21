from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rul.data import (
    add_rul_labels,
    align_test_rul,
    apply_scaler,
    fit_scaler,
    load_test,
    load_train,
    make_windows,
    select_features,
    split_engines,
    validation_cutoffs,
)


DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def labeled_train():
    return add_rul_labels(load_train(DATA_DIR / "train_FD001.txt"))


@pytest.fixture(scope="module")
def engine_split(labeled_train):
    train_units, val_units = split_engines(labeled_train["unit"].unique().tolist())
    train = labeled_train.loc[labeled_train["unit"].isin(train_units)]
    val = labeled_train.loc[labeled_train["unit"].isin(val_units)]
    return train, val


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


def test_split_has_no_overlap_and_is_reproducible(labeled_train):
    units = labeled_train["unit"].unique().tolist()
    train, val = split_engines(units)

    assert len(train) == 80
    assert len(val) == 20
    assert set(train).isdisjoint(val)
    assert set(train) | set(val) == set(units)
    assert (train, val) == split_engines(units)


def test_features_drop_constant_columns(engine_split):
    train, _ = engine_split
    features = select_features(train)
    candidates = train.filter(regex=r"^(op_|s_)")

    assert 0 < len(features) < len(candidates.columns)
    assert features == candidates.columns[candidates.std() > 1e-4].tolist()


def test_scaler_uses_training_engines_only(engine_split, labeled_train):
    train, _ = engine_split
    features = select_features(train)
    train_scaler = fit_scaler(train, features)
    all_scaler = fit_scaler(labeled_train, features)
    scaled = apply_scaler(train, train_scaler)[features]

    assert train_scaler != all_scaler
    assert ((0 <= scaled) & (scaled <= 1)).all().all()


def test_windows_have_no_future_cycles(engine_split, labeled_train):
    train, _ = engine_split
    features = select_features(train)
    rows = labeled_train.loc[labeled_train["unit"].isin([1, 2])]
    shuffled = rows.sample(frac=1, random_state=7)
    scaled = apply_scaler(shuffled, fit_scaler(train, features))

    windows = make_windows(scaled, features)
    row_40 = np.flatnonzero((scaled["unit"] == 1) & (scaled["cycle"] == 40))[0]
    expected = scaled.loc[(scaled["unit"] == 1) & scaled["cycle"].between(11, 40)]
    np.testing.assert_allclose(windows[row_40], expected.sort_values("cycle")[features])


def test_windows_pad_short_engine():
    rows = pd.DataFrame({"unit": 1, "cycle": range(1, 11), "s_2": range(10, 20)})
    windows = make_windows(rows, ["s_2"])

    assert windows.shape == (10, 30, 1)
    np.testing.assert_array_equal(windows[0], np.full((30, 1), 10))


def test_cutoffs_exclude_final_cycle(engine_split):
    _, val = engine_split
    cutoffs = validation_cutoffs(val)

    assert cutoffs.columns.equals(val.columns)
    assert (cutoffs["rul_uncapped"] >= 1).all()
    assert cutoffs.groupby("unit").size().to_dict() == dict.fromkeys(val["unit"].unique(), 5)
