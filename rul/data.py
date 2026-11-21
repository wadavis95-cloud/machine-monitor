from pathlib import Path

import numpy as np
import pandas as pd

from loader import load_data


RUL_CAP = 125
WINDOW = 30
SEED = 42
N_VAL = 20


def load_train(path: Path) -> pd.DataFrame:
    """Read the engine runs that end at failure."""
    return load_data(path)


def load_test(test_path: Path, rul_path: Path) -> tuple[pd.DataFrame, pd.Series]:
    """Read the shortened test runs and each engine's final observed RUL."""
    rows = load_data(test_path)
    labels = pd.read_csv(rul_path, sep=r"\s+", header=None, dtype="int64")
    if labels.shape[1] != 1:
        raise ValueError("Expected a single column of test RUL values.")
    return rows, align_test_rul(rows, labels[0].tolist())


def align_test_rul(test_df: pd.DataFrame, rul_values: list[int]) -> pd.Series:
    """Match label row 1 to engine 1, regardless of the test rows' order."""
    units = sorted(test_df["unit"].unique())
    if units != list(range(1, len(rul_values) + 1)):
        raise ValueError("Expected one test RUL value per engine numbered from 1.")
    return pd.Series(rul_values, index=pd.Index(units, name="unit"), dtype="int64")


def add_rul_labels(df: pd.DataFrame, cap: int = RUL_CAP) -> pd.DataFrame:
    """Add actual and capped cycles left for runs that end at failure."""
    labeled = df.copy()
    final_cycles = labeled.groupby("unit")["cycle"].transform("max")
    labeled["rul_uncapped"] = final_cycles - labeled["cycle"]
    labeled["rul_true"] = labeled["rul_uncapped"].clip(upper=cap)
    return labeled


def split_engines(
    units: list[int], n_val: int = N_VAL, seed: int = SEED
) -> tuple[list[int], list[int]]:
    """Keep each engine's entire history in one group."""
    unique_units = sorted(set(units))
    if not 0 <= n_val <= len(unique_units):
        raise ValueError("Validation engine count must fit the number of unique engines.")
    shuffled = np.random.default_rng(seed).permutation(unique_units).tolist()
    return sorted(shuffled[n_val:]), sorted(shuffled[:n_val])


def select_features(train_df: pd.DataFrame) -> list[str]:
    """Keep sensor and setting columns that vary on training engines."""
    candidates = [name for name in train_df.columns if name.startswith(("op_", "s_"))]
    spread = train_df[candidates].std()
    return spread[spread > 1e-4].index.tolist()


def fit_scaler(train_df: pd.DataFrame, features: list[str]) -> dict[str, tuple[float, float]]:
    """Record each feature's lowest and highest values on training engines."""
    return {
        feature: (float(train_df[feature].min()), float(train_df[feature].max()))
        for feature in features
    }


def apply_scaler(df: pd.DataFrame, scaler: dict) -> pd.DataFrame:
    """Use the training range to scale readings, allowing values outside it."""
    scaled = df.copy()
    for feature, (low, high) in scaler.items():
        # A constant training feature maps to zero without dividing by zero.
        span = high - low or 1.0
        scaled[feature] = (scaled[feature] - low) / span
    return scaled


def make_windows(df: pd.DataFrame, features: list[str], window: int = WINDOW) -> np.ndarray:
    """Build one window per input row, ending at that row's cycle."""
    if window < 1:
        raise ValueError("Window size must be at least one cycle.")
    values = df[features].to_numpy(dtype=float)
    cycles = df["cycle"].to_numpy()
    windows = np.empty((len(df), window, len(features)), dtype=values.dtype)
    steps = np.arange(window)

    for positions in df.groupby("unit").indices.values():
        # Read each engine in cycle order, then place its windows back in input order.
        ordered = positions[np.argsort(cycles[positions])]
        readings = values[ordered]
        padding = np.repeat(readings[:1], window - 1, axis=0)
        padded = np.concatenate((padding, readings))

        # Each window starts one row later than the previous one.
        starts = np.arange(len(readings))[:, None]
        windows[ordered] = padded[starts + steps]

    return windows


def validation_cutoffs(val_df: pd.DataFrame, per_engine: int = 5, seed: int = SEED) -> pd.DataFrame:
    """Sample distinct pre-failure cycles from each validation engine."""
    if val_df.empty:
        return val_df.copy()

    rng = np.random.default_rng(seed)
    cutoffs = []
    for _, engine in val_df.sort_values("cycle").groupby("unit"):
        # Stop before failure to mimic the shortened official test runs.
        last_cycle = engine["cycle"].max()
        before_failure = engine.loc[engine["cycle"].between(1, last_cycle - 1)]
        cutoffs.append(before_failure.sample(n=per_engine, random_state=rng))
    return pd.concat(cutoffs)
