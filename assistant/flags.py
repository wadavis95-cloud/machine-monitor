import pandas as pd


def t24_band(data: pd.DataFrame, unit: int) -> tuple[float, float]:
    """Use the 5th and 95th percentiles of other engines' first 30 cycles."""
    early_cycles = data["cycle"].between(1, 30)
    other_units = data["unit"] != unit
    reference = data.loc[early_cycles & other_units, "s_2"]
    lower, upper = reference.quantile([0.05, 0.95])
    return float(lower), float(upper)


def flag_level(t24: list[float], lower: float, upper: float) -> str:
    """Return red if the last five readings are all outside the band.

    Otherwise return yellow if at least three of the last ten are above the
    upper limit, or none.
    """
    last_five = t24[-5:]
    if len(last_five) == 5 and all(
        reading < lower or reading > upper for reading in last_five
    ):
        return "red"

    high_count = sum(1 for reading in t24[-10:] if reading > upper)
    if high_count >= 3:
        return "yellow"
    return "none"
