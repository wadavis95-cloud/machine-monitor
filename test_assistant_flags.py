import pandas as pd
import pytest

from assistant.flags import flag_level, t24_band


def test_flag_none_when_inside_band():
    assert flag_level([15] * 10, 10, 20) == "none"


def test_flag_yellow_three_highs_in_last_ten():
    readings = [15] * 7 + [21, 15, 21, 15, 21]
    assert flag_level(readings, 10, 20) == "yellow"


def test_flag_ignores_highs_older_than_ten():
    readings = [21, 21, 21] + [15] * 10
    assert flag_level(readings, 10, 20) == "none"


def test_flag_red_five_consecutive_outside():
    readings = [15] * 5 + [9, 21, 9, 21, 9]
    assert flag_level(readings, 10, 20) == "red"


def test_flag_red_beats_yellow():
    assert flag_level([21] * 5, 10, 20) == "red"


def test_flag_short_history():
    assert flag_level([], 10, 20) == "none"
    assert flag_level([21, 21], 10, 20) == "none"


def test_band_excludes_own_unit():
    data = pd.DataFrame(
        [(1, 1, -1000), (1, 30, 1000), (2, 1, 10), (3, 30, 20), (3, 31, 2000)],
        columns=["unit", "cycle", "s_2"],
    )

    # Only 10 and 20 count, with the percentiles 5% and 95% of the way between them.
    assert t24_band(data, 1) == pytest.approx((10.5, 19.5))
