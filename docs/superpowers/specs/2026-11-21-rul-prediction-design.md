# Remaining Useful Life (RUL) prediction: design

Status: draft for user approval (builder-checked by Codex) · 2026-11-21

## Intent and why
Add predictions of how many cycles each engine has left before failure (remaining useful life, RUL) to Machine Monitor. The project exists for **learning and interview prep**: the user must be able to explain every layer. The user holds an NVIDIA Fundamentals of Deep Learning cert, so the deep-learning rung should be real, not a toy. The interview story is a **ladder of models compared fairly on untouched data**: "the LSTM cut RMSE from X to Y compared with a linear baseline, on NASA's official test set."

## Goals
1. A reproducible training pipeline that trains three models (the ladder) and scores them on NASA's official FD001 test set.
2. A saved prediction for every (engine, cycle) in the replayed training file, which the dashboard shows during the replay: "Est. ~N cycles left".
3. An honest UI: each engine is labeled **seen in training** or **validation (unseen)**.
4. A results report (a markdown table) the user can quote in interviews.
5. `LEARNING.md` rows for each new ML or engineering concept, in plain words.

## Non-goals (for now)
- Running the model inside Flask (live inference). Possible later upgrade.
- An LLM/RAG assistant on top ("why is engine 34 flagged?"). A separate follow-up project.
- The FD002–FD004 datasets, large hyperparameter searches, GPU/cloud training.

## Anti-goals (failure even if it "works")
- **Leakage:** the test set influences training or model choice; rows from one engine end up on both sides of a split; scaling statistics are computed on non-training data; the model uses future cycles.
- The Flask app needs PyTorch to start, or breaks when the predictions file is missing.
- Code the user can't follow: clever abstractions, magic, or one giant script.

## Constraints
- Python, the existing `.venv`, Flask app, pandas loader. Keep changes small and readable (see AGENTS.md).
- ML dependencies (torch, scikit-learn) go in a separate `requirements-ml.txt`. The web app must keep working without them.
- Training must run on a MacBook CPU in a few minutes (Apple MPS optional).
- The app's `.venv` runs Python 3.14 (ARM64). Pin versions of torch and scikit-learn that have wheels for it. If there aren't any, create a separate `.venv-ml` on Python 3.12 or 3.13 just for training. That's fine, because the app never imports them. *(Claude's call)*
- Fixed random seeds so results are reproducible.

## Data
- **Train/validation:** the existing `data/train_FD001.txt` (100 engines run to failure). Split **by engine**: 80 for training, 20 for validation, with a fixed seed. *(Claude's call)*
- **Test:** NASA's official `test_FD001.txt` (100 engines cut off partway through) and `RUL_FD001.txt` (the true RUL at each engine's last cycle). Download these from NASA's Prognostics Center of Excellence data repository (C-MAPSS). **Use them once, for final scoring only.**
- **Test-set format:**
  - `test_FD001.txt` engines stop *before* failure, so the formula "final cycle − current cycle" does **not** apply to them.
  - `RUL_FD001.txt` is a headerless list of 100 numbers: the true RUL at each test engine's last observed cycle, in engine-ID order. Parse it separately and check that it lines up by engine ID.
  - **Score one prediction per test engine, at its last observed cycle.**
  - Report RMSE against the true RUL **capped at 125** (the main number, comparable to the literature) and against the **uncapped** true RUL. *(Claude's call)*
- **Validation must mimic the test set** *(Claude's call)*:
  - Full validation trajectories end at RUL 0, which makes them easier than the test engines.
  - So, for tuning, cut each validation engine at a few random earlier cycles (fixed seed) and score the prediction at each cut-off point, the same way the test set is scored.
- **Download:** the official ZIPs are at https://data.nasa.gov/docs/legacy/CMAPSSData.zip and the PCoE S3 archive. Codex's sandbox couldn't reach them, so download outside the sandbox. If that fails, the user downloads the ZIP by hand into `data/`.
- **Labels:** the true RUL of each row = the engine's final cycle − the current cycle. **Cap it at 125** (piecewise-linear target, standard for this dataset: early in life an engine is healthy and its RUL isn't predictable from its sensors). *(Claude's call; explain it in LEARNING.md)*
- **Features:** drop the sensors and settings that stay roughly constant in FD001 (confirm by variance on the training engines). Fit min-max or standard scaling on the **training engines only**.

## Approaches considered
1. **The ladder: baseline → classic ML → LSTM, all compared on the same test set (chosen).** It proves the neural network earns its complexity, and it's the strongest interview story. Costs more steps, but A and B are small and share data prep with C.
2. **Straight to the neural network.** Faster, but gives one number with nothing to compare it to ("compared to what?").
3. **Neural network plus an LLM assistant.** It uses both certs, but it's really a second project, so it's deferred.

Second choice: **when the model runs.** **Train offline and save predictions to a file (chosen)** rather than loading the model in Flask. It keeps the web app light and fast and keeps PyTorch out of the app. Live inference is a documented upgrade path.

## The ladder
| Rung | Model | Input | Why it's on the ladder |
|---|---|---|---|
| A | Linear regression (scikit-learn) | The current cycle's scaled readings | The simplest real baseline |
| B | Random forest or gradient boosting (scikit-learn) | Hand-made window features over the last 30 cycles (mean, slope) | Classic ML with feature engineering |
| C | LSTM (PyTorch) | A sliding window of the last 30 cycles of scaled readings | Learns patterns over time directly |

*(Claude's call: rung A was described earlier as a "trend line". A linear regression is the cleaner, standard baseline. The window length of 30 is the common choice for FD001.)*
- Engines with fewer cycles than the window: pad the start (rungs B and C); the builder chooses how.
- Tune using **validation engines only**, with the cut-off scoring described above.
- **Freeze all three rungs and the scoring code before anyone runs the test set.** The test set is scored once, in the final build step, for all three rungs together.
- **Metrics:** RMSE (main) plus NASA's asymmetric score function, which penalizes late predictions more because predicting failure too late is dangerous.

## Outputs
- `data/predictions_FD001.csv`: `unit, cycle, split (train|val), rul_true, rul_linear, rul_trees, rul_lstm`, covering every row of `train_FD001.txt`.
- `reports/rul_results.md`: a table of validation and test RMSE and score per rung, plus run date and seeds.
- Model weights saved under `models/` (gitignored). The predictions CSV and the report are committed.

## Code layout (suggested; the builder may adjust)
- `rul/data.py`: load train/test, build labels, split by engine, choose features, scaling, windows.
- `rul/models.py`: the three models.
- `rul/train.py`: entry point (`python -m rul.train`): trains, evaluates, writes outputs.
- Small, readable functions, with docstrings in plain words.

## App changes
- At startup, `app.py` loads `data/predictions_FD001.csv` **if present**. If it's absent, the app works exactly as today (graceful degradation).
- `/live` (and `/cycle`) readings gain `rul_pred` (from gradient boosting, the shipped model; see the decision log) and `split`.
- The dashboard shows "Est. ~N cycles left" next to the readings, plus a badge: **seen in training** / **validation (unseen)**. Optional: the true RUL alongside it, for comparison.
- CSV handling *(Claude's call)*:
  - Predictions are clipped to [0, 125] and rounded to whole cycles. 0 stays 0.
  - If a row is missing or isn't a valid number, `rul_pred` is left out of that reading, and the dashboard shows nothing for it.
  - Duplicate (unit, cycle) rows fail loudly at startup.
- The dashboard's existing warning bands (fleet range from cycles 1–30) stay **unchanged**. They're separate from the model's feature scaling.

## Testing
- pytest for data prep:
  - no engine appears in both train and val;
  - scaling statistics come from the training engines only;
  - labels are correct and capped;
  - windows contain no future cycles;
  - test RUL alignment matches `RUL_FD001.txt`.
- The model code gets a quick smoke test (a tiny run on 2 engines). Training quality isn't unit-tested.
- App tests: with the CSV, `/live` includes `rul_pred` and `split`; without it, everything still passes.
- JS test: the RUL text and badge render; they're absent without the field.

## Build order (each step reviewed and explained before the next)
1. Set up the ML environment, download the test data, then data prep plus leakage tests.
2. Rung A plus the evaluation code (**validation scores only**).
3. Rung B (validation only).
4. Rung C, the LSTM (validation only).
5. Freeze the models, then run the **one-time test scoring** and write `reports/rul_results.md`.
6. Predictions CSV, then app and dashboard integration.

## Left to the builder
- Exact sensor drop list (by variance), scaler type, LSTM size, epochs, learning rate, padding method, and whether rung B is a random forest or gradient boosting. Each choice is recorded in the report or LEARNING.md with a one-line reason.

## Decision log
- **2026-11-21: ship gradient boosting (`rul_trees`), not the LSTM.** On validation the two tied: LSTM 13.76 ± 0.55 vs boosting 13.96 ± 0.02 RMSE, so the gap is within seed noise. The LSTM's validation score is also slightly optimistic, because early stopping used the same engines. Boosting is about 25× more stable across seeds, simpler, and has no PyTorch dependency. This decision was made **before** the test set was scored, so the test set can't influence which model ships. The user made this call.
