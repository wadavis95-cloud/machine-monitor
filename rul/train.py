"""Train the frozen RUL models and report their validation and holdout scores."""

import argparse
from datetime import date
from pathlib import Path
from platform import python_version
from tempfile import mkdtemp

import joblib
import numpy as np
import pandas as pd
import sklearn
import torch

from rul.data import (
    N_VAL, RUL_CAP, SEED, WINDOW, add_rul_labels, apply_scaler, fit_scaler,
    load_test, load_train, select_features, split_engines, validation_cutoffs,
)
from rul.evaluate import nasa_score, rmse
from rul.models import LinearRUL, LSTMRUL, TreesRUL


ROOT = Path(__file__).resolve().parents[1]
SHIP_DECISION = "Shipped model (decided on validation, 2026-11-21): gradient boosting"


def score_on_test(models, scaler, data_dir: Path) -> dict[str, tuple[float, float, float]]:
    """Score one prediction per engine, at its last observed test cycle."""
    rows, truth = load_test(data_dir / "test_FD001.txt", data_dir / "RUL_FD001.txt")
    rows = apply_scaler(rows.reset_index(drop=True), scaler)
    last_rows = rows.groupby("unit")["cycle"].idxmax()
    # Match labels by engine ID even if the input rows are shuffled.
    truth = truth.reindex(last_rows.index)
    capped = truth.clip(upper=RUL_CAP)

    scores = {}
    for name, model in models.items():
        # Predict from the full histories so the final windows keep earlier cycles.
        predictions = model.predict(rows)[last_rows.to_numpy()]
        scores[name] = rmse(capped, predictions), rmse(truth, predictions), nasa_score(truth, predictions)
    return scores


def write_scores(report: Path, val_scores, test_scores) -> None:
    with report.open("a") as output:
        output.write(
            "| Rung | Val RMSE (capped) | Val NASA (capped) | Test RMSE (capped) |"
            " Test RMSE (uncapped) | Test NASA (uncapped) |\n"
            "|---|---:|---:|---:|---:|---:|\n"
        )
        for name, val in val_scores.items():
            values = [f"{value:.4f}" for value in (*val, *test_scores.get(name, ()))]
            if name not in test_scores:
                values.extend(["—"] * 3)
            output.write(f"| {name} | {' | '.join(values)} |\n")

        if test_scores:
            val_rmse, val_nasa = val_scores["trees"]
            capped, uncapped, test_nasa = test_scores["trees"]
            output.write(
                "\n## Shipped model card\n\n"
                "- **Model and data.** Gradient boosting on 30-cycle means and slopes. "
                "Trained on 80 simulated NASA C-MAPSS FD001 engines. "
                "Validated on 100 cutoffs from 20 separate engines and tested on the last observed cycle "
                "of each of the 100 official test engines.\n"
                "- **Intended use.** A learning demo that displays estimates during historical replay.\n"
                f"- **Metrics.** Validation RMSE {val_rmse:.4f} cycles and NASA score {val_nasa:.4f} "
                f"on capped labels. Test RMSE {capped:.4f} capped and {uncapped:.4f} uncapped, "
                f"with NASA score {test_nasa:.4f} against uncapped labels.\n"
                "- **Limitations.** FD001 simulates one operating condition and one fault mode. "
                "Training targets are capped at 125 cycles. The comparison LSTM varied more across "
                "seeds and used the validation cutoffs for early stopping.\n"
                "- **When to avoid it.** Keep it out of real maintenance, safety, or scheduling decisions "
                "and predictions for other operating conditions, faults, or engine fleets.\n"
            )


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="Run a small validation-only smoke check.")
    parser.add_argument("--out", type=Path, help="Root directory for the report and model bundle.")
    args = parser.parse_args(argv)

    out = args.out
    if out is None:
        out = Path(mkdtemp(prefix="rul-quick-")) if args.quick else ROOT
    data_dir = ROOT / "data"
    torch.set_num_threads(2)  # Match the CPU configuration used in the validation experiments.

    rows = add_rul_labels(load_train(data_dir / "train_FD001.txt"))
    units = sorted(rows["unit"].unique())
    if args.quick:
        units = units[:6]
    train_units, val_units = split_engines(units, n_val=2 if args.quick else N_VAL)
    train = rows.loc[rows["unit"].isin(train_units)]
    val = rows.loc[rows["unit"].isin(val_units)]
    features = select_features(train)
    scaler = fit_scaler(train, features)
    train = apply_scaler(train, scaler)
    val = apply_scaler(val, scaler)
    cutoffs = validation_cutoffs(val)
    cutoff_positions = val.index.get_indexer(cutoffs.index)

    models = {
        "linear": LinearRUL(),
        "trees": TreesRUL(),
        "lstm": LSTMRUL(epochs=1) if args.quick else LSTMRUL(),
    }
    val_scores = {}
    for name, model in models.items():
        if name == "lstm":
            model.fit(train, features, val_df=val)
        else:
            model.fit(train, features)
        prediction = model.predict(val)[cutoff_positions]
        truth = cutoffs["rul_true"]
        val_scores[name] = rmse(truth, prediction), nasa_score(truth, prediction)

    # Save the fitted models and preprocessing before opening the official holdout.
    model_dir = out / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump({"models": models, "features": features, "scaler": scaler}, model_dir / "rul.joblib")

    report = out / "reports" / "rul_results.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    mode = "Quick validation-only smoke run." if args.quick else "Frozen FD001 evaluation."
    report.write_text(
        f"# FD001 remaining useful life results\n\n{SHIP_DECISION}\n\n"
        f"{mode} Run date {date.today().isoformat()}.\n\n"
        f"- **Seeds:** {SEED} for the engine split, validation cutoffs, boosting, and LSTM.\n"
        f"- **Split:** {len(train_units)} training engines, {len(val_units)} validation engines, "
        f"{len(cutoffs)} validation cutoffs. Window length {WINDOW}, label cap {RUL_CAP}.\n"
        f"- **Features:** {', '.join(features)}. Feature selection and min-max scaling use training engines only.\n"
        f"- **Versions:** Python {python_version()}, NumPy {np.__version__}, pandas {pd.__version__}, "
        f"scikit-learn {sklearn.__version__}, PyTorch {torch.__version__}, joblib {joblib.__version__}.\n\n"
    )

    test_scores = {} if args.quick else score_on_test(models, scaler, data_dir)
    write_scores(report, val_scores, test_scores)
    print(f"Report written to {report}")


if __name__ == "__main__":
    main()
