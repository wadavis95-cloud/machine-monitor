import numpy as np
import pandas as pd
import pytest

from rul import train


@pytest.fixture
def quick_rows(monkeypatch):
    rows = pd.DataFrame(
        [
            {"unit": unit, "cycle": cycle, "s_2": unit + cycle * 0.5}
            for unit in range(1, 7)
            for cycle in range(1, 9)
        ]
    )

    def forbid_holdout(*args):
        pytest.fail("Quick mode must leave the official holdout untouched.")

    monkeypatch.setattr(train, "load_train", lambda path: rows)
    monkeypatch.setattr(train, "load_test", forbid_holdout)
    return rows


def test_train_quick_writes_report(tmp_path, quick_rows):
    train.main(["--quick", "--out", str(tmp_path)])

    report = (tmp_path / "reports" / "rul_results.md").read_text()
    for rung in ("linear", "trees", "lstm"):
        assert f"| {rung} |" in report


def test_predictions_clipped_and_rounded(tmp_path):
    rows = pd.DataFrame({
        "unit": [1, 1, 2], "cycle": [1, 2, 1], "split": ["train", "train", "val"],
        "rul_true": [1, 0, 0],
    })
    predictions = {name: np.array([-3.2, 130.7, 42.5]) for name in ("linear", "trees", "lstm")}
    path = tmp_path / "predictions.csv"
    train.write_predictions(rows, predictions, path)

    exported = pd.read_csv(path, comment="#")
    for name in predictions:
        column = exported[f"rul_{name}"]
        assert column.tolist() == [0, 125, 42]
        assert pd.api.types.is_integer_dtype(column)


def test_predictions_cover_every_row(tmp_path, quick_rows):
    train.main(["--quick", "--out", str(tmp_path)])

    path = tmp_path / "data" / "predictions_FD001.csv"
    exported = pd.read_csv(path, comment="#")
    assert list(exported.columns) == [
        "unit", "cycle", "split", "rul_true", "rul_linear", "rul_trees", "rul_lstm",
    ]
    assert len(exported) == len(quick_rows)
    assert not exported.duplicated(["unit", "cycle"]).any()
    pd.testing.assert_frame_equal(exported[["unit", "cycle"]], quick_rows[["unit", "cycle"]])
    assert exported.groupby("split")["unit"].nunique().to_dict() == {"train": 4, "val": 2}
