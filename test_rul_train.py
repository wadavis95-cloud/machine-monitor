import pandas as pd
import pytest

from rul import train


def test_train_quick_writes_report(tmp_path, monkeypatch):
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
    train.main(["--quick", "--out", str(tmp_path)])

    report = (tmp_path / "reports" / "rul_results.md").read_text()
    for rung in ("linear", "trees", "lstm"):
        assert f"| {rung} |" in report
