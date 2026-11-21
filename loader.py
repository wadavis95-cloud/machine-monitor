import pandas as pd


def load_data(path):
    """Read a headerless C-MAPSS data file into a DataFrame."""
    columns = ["unit", "cycle", "op_1", "op_2", "op_3"]
    columns += [f"s_{number}" for number in range(1, 22)]
    return pd.read_csv(path, sep=r"\s+", header=None, names=columns)
