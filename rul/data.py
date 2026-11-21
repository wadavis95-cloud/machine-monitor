from pathlib import Path

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
