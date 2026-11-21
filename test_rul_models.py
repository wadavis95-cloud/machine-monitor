from pathlib import Path
from time import perf_counter

import numpy as np

from rul.data import add_rul_labels, apply_scaler, fit_scaler, load_train, select_features
from rul.models import LSTMRUL, LinearRUL, TreesRUL


def test_linear_smoke():
    data = load_train(Path(__file__).parent / "data" / "train_FD001.txt")
    train = add_rul_labels(data.loc[data["unit"].isin([1, 2])])
    features = select_features(train)
    scaled = apply_scaler(train, fit_scaler(train, features))

    model = LinearRUL()
    model.fit(scaled, features)
    predictions = model.predict(scaled)

    assert predictions.shape == (len(scaled),)
    assert np.isfinite(predictions).all()


def test_trees_smoke():
    data = load_train(Path(__file__).parent / "data" / "train_FD001.txt")
    train = add_rul_labels(data.loc[data["unit"].isin([1, 2])])
    features = select_features(train)
    scaled = apply_scaler(train, fit_scaler(train, features))

    model = TreesRUL()
    model.fit(scaled, features)
    predictions = model.predict(scaled)

    assert predictions.shape == (len(scaled),)
    assert np.isfinite(predictions).all()


def test_lstm_smoke():
    started = perf_counter()
    data = load_train(Path(__file__).parent / "data" / "train_FD001.txt")
    train = add_rul_labels(data.loc[data["unit"].isin([1, 2])])
    features = select_features(train)
    scaled = apply_scaler(train, fit_scaler(train, features))

    model = LSTMRUL(epochs=1)
    model.fit(scaled, features)
    predictions = model.predict(scaled)

    assert predictions.shape == (len(scaled),)
    assert np.isfinite(predictions).all()
    assert perf_counter() - started < 30
