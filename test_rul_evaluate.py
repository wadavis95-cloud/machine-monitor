import pytest

from rul.evaluate import nasa_score, rmse


def test_rmse_known_value():
    assert rmse([0, 0], [3, 4]) == pytest.approx(3.5355, abs=0.0001)


def test_nasa_score_penalizes_late_more():
    assert nasa_score([50], [60]) > nasa_score([50], [40])
    assert nasa_score([50], [50]) == 0
