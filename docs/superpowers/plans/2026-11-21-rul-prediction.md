# RUL Prediction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **In this project:** Claude sends one task at a time to Codex (codex-run skill), reviews it, and explains it to the user before the next task. Don't start the next task until the user says so.

**Goal:** Train a ladder of three remaining-useful-life (RUL) models (linear, trees, LSTM) on NASA C-MAPSS FD001, score them once on the official test set, and show the LSTM's per-cycle prediction in the dashboard.

**Architecture:** An offline `rul/` package does the data prep, the models, the evaluation, and a training entry point. It writes `data/predictions_FD001.csv` and `reports/rul_results.md`. `app.py` reads the CSV at startup *if present* and attaches `rul_pred` and `split` to readings. The app never imports torch or scikit-learn.

**Tech Stack:** Python, pandas, numpy, scikit-learn, PyTorch (CPU), Flask, pytest, node:test.

**Spec:** `docs/superpowers/specs/2026-11-21-rul-prediction-design.md`

## Global Constraints
- `RUL_CAP = 125`, `WINDOW = 30`, `SEED = 42`, `N_VAL = 20` (80 train / 20 val engines). All live in `rul/data.py`.
- The test set (`test_FD001.txt`, `RUL_FD001.txt`) is read **only** by `rul.train` in Task 6. No other task loads it, except the parsing unit test in Task 1, which only checks shape and alignment.
- Feature selection and scaling are fitted on **training engines only**.
- ML deps go in `requirements-ml.txt` and must never be imported by `app.py`, `loader.py`, or `templates/`.
- `$ML_PY` = the Python chosen in Task 1 (`.venv/bin/python`, or `.venv-ml/bin/python` if torch has no 3.14 wheel).
- Pytest command form: `$ML_PY -B -m pytest -q -p no:cacheprovider <files>`. App tests run with `.venv/bin/python`.
- Keep code beginner-readable: small functions, plain-words docstrings, no new abstractions. Append concepts to `LEARNING.md` in every task.
- Commit after each task only with the user's OK. Claude asks.

## Review Focus
1. **A short engine** (fewer cycles than `WINDOW`): windows must pad, not crash or drop rows. Test in Task 2: `test_windows_pad_short_engine`.
2. **The test-set file order isn't the RUL file order:** alignment must go by engine ID, not position. Test in Task 1: `test_rul_vector_aligns_by_unit`.
3. **Negative or above-cap predictions** from a model must be clipped to [0, 125] in the CSV. Test in Task 7: `test_predictions_clipped_and_rounded`.
4. **The predictions CSV is missing or partial** at app startup: the app runs, and readings simply lack `rul_pred`. Test in Task 8: `test_live_without_predictions_file`, `test_live_missing_row_omits_rul`.
5. **Duplicate (unit, cycle) rows in the CSV** must fail loudly at startup. Test in Task 8: `test_duplicate_prediction_rows_raise`.

## File map
| File | Responsibility |
|---|---|
| `requirements-ml.txt` | Pinned ML deps + a header comment naming the Python used |
| `rul/__init__.py` | Empty |
| `rul/data.py` | Constants, loading, labels, split, features, scaling, windows, val cut-offs |
| `rul/evaluate.py` | `rmse`, `nasa_score` |
| `rul/models.py` | Three model wrappers sharing `fit` / `predict` |
| `rul/train.py` | `python -m rul.train`: orchestrates, writes outputs |
| `test_rul_data.py`, `test_rul_evaluate.py`, `test_rul_models.py`, `test_rul_train.py` | Tests (repo root, matching existing layout) |
| `app.py`, `templates/index.html`, `test_app.py`, `test_dashboard.js` | Integration (Tasks 8–9) |
| `.gitignore` | Add `models/`, `.venv-ml/` |

---

### Task 1: ML environment, test data, loading and labels
**Files:**
- Create: `requirements-ml.txt`, `rul/__init__.py`, `rul/data.py`, `test_rul_data.py`
- Add: `data/test_FD001.txt`, `data/RUL_FD001.txt`
- Modify: `.gitignore`

**Interfaces:**
- Produces:
  - Constants `RUL_CAP`, `WINDOW`, `SEED`, `N_VAL`.
  - `load_train(path: Path) -> pd.DataFrame`. Reuses `loader.load_data`; columns `unit, cycle, op_1..op_3, s_1..s_21`.
  - `load_test(test_path: Path, rul_path: Path) -> tuple[pd.DataFrame, pd.Series]`. Returns the test rows plus a Series indexed by `unit` (1..100), holding the true uncapped RUL at each unit's last observed cycle.
  - `align_test_rul(test_df: pd.DataFrame, rul_values: list[int]) -> pd.Series`. Maps the sorted unique units of `test_df` to `rul_values` (value *i* → unit *i+1*). Used by `load_test`.
  - `add_rul_labels(df: pd.DataFrame, cap: int = RUL_CAP) -> pd.DataFrame`. Adds `rul_uncapped = max cycle of unit − cycle` and `rul_true = min(rul_uncapped, cap)`. Only valid for run-to-failure data.

- [ ] **Step 1:** Install torch and scikit-learn into `.venv`. If either has no wheel for Python 3.14, create `.venv-ml` with Python 3.12 or 3.13, plus pandas, numpy, pytest, torch and scikit-learn. Pin the exact versions in `requirements-ml.txt`, with a first-line comment `# Python used: <path> <version>`. Check: `$ML_PY -c "import torch, sklearn; print(torch.__version__, sklearn.__version__)"` prints the versions.
- [ ] **Step 2:** Download `CMAPSSData.zip` (https://data.nasa.gov/docs/legacy/CMAPSSData.zip, or the PCoE S3 archive) outside the sandbox. Extract only `test_FD001.txt` and `RUL_FD001.txt` into `data/`. If both downloads fail, stop and report `status: blocked`, because the user will download it by hand. Check: `wc -l data/RUL_FD001.txt` gives 100.
- [ ] **Step 3: Write the failing tests** in `test_rul_data.py`:
  - `test_labels_count_down_to_zero`: for unit 1, `rul_uncapped` at the last cycle == 0, and at the first cycle == (last cycle − 1).
  - `test_labels_capped_at_125`: `df.rul_true.max() == 125`, and `(df.rul_true <= df.rul_uncapped).all()`.
  - `test_load_test_shapes`: the Series has length 100 with index 1..100. Every test unit has ≥ 1 row.
  - `test_rul_vector_aligns_by_unit`: `align_test_rul` on shuffled test rows returns the same unit → RUL mapping as on unshuffled rows.
- [ ] **Step 4:** Run them and verify they FAIL (`ImportError`).
- [ ] **Step 5:** Implement the three functions and the constants in `rul/data.py`. `RUL_FD001.txt` is a headerless single column. Row *i* belongs to unit *i+1*.
- [ ] **Step 6:** Run `$ML_PY -B -m pytest -q -p no:cacheprovider test_rul_data.py`. Expected: 4 passed. Also run the existing app tests with `.venv/bin/python`: all pass.
- [ ] **Step 7:** Add `models/` and `.venv-ml/` to `.gitignore`. Add LEARNING.md rows for *RUL label*, *capping at 125*, and *virtual environment*. Ask before committing: `feat(rul): ML env, test data, loading and RUL labels`.

### Task 2: Split, features, scaling, windows, validation cut-offs (the leakage guards)
**Files:** Modify `rul/data.py`, `test_rul_data.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `split_engines(units: list[int], n_val: int = N_VAL, seed: int = SEED) -> tuple[list[int], list[int]]`.
  - `select_features(train_df: pd.DataFrame) -> list[str]`. Keeps the `op_*`/`s_*` columns whose std on `train_df` is > 1e-4.
  - `fit_scaler(train_df: pd.DataFrame, features: list[str]) -> dict[str, tuple[float, float]]`. Returns a min-max per feature.
  - `apply_scaler(df: pd.DataFrame, scaler: dict) -> pd.DataFrame`. Scales to roughly [0, 1]. Values outside the training range are allowed, not clipped.
  - `make_windows(df: pd.DataFrame, features: list[str], window: int = WINDOW) -> np.ndarray`. Shape `(len(df), window, len(features))`, in df row order. The window for a row holds that unit's rows ending **at** that cycle. Short histories are padded at the front by repeating the unit's first row.
  - `validation_cutoffs(val_df: pd.DataFrame, per_engine: int = 5, seed: int = SEED) -> pd.DataFrame`. Returns `per_engine` random rows per val unit, drawn from cycles 1 .. (last − 1), with all columns.

- [ ] **Step 1: Write the failing tests:**
  - `test_split_has_no_overlap_and_is_reproducible`: train ∩ val == ∅, lengths are 80/20, and two calls give equal results.
  - `test_features_drop_constant_columns`: none of the returned columns has std ≤ 1e-4 on the train engines.
  - `test_scaler_uses_training_engines_only`: the scaler built from train rows differs from one built on all rows for at least one feature. Train rows scale into [0, 1].
  - `test_windows_have_no_future_cycles`: for unit 1 at cycle 40, the last window step equals the scaled row at cycle 40, and the first step equals cycle 11.
  - `test_windows_pad_short_engine`: a 10-cycle synthetic unit gives shape `(10, 30, n)`, and `window[0]` is 30 copies of row 1.
  - `test_cutoffs_exclude_final_cycle`: every cut-off has `rul_uncapped ≥ 1`, and the cut-offs contain exactly 5 rows per val unit.
- [ ] **Step 2:** Run the tests and verify they FAIL.
- [ ] **Step 3:** Implement the functions. Vectorize `make_windows` per unit with numpy.
- [ ] **Step 4:** Run `test_rul_data.py`. Expected: 10 passed.
- [ ] **Step 5:** Add LEARNING.md rows for *data leakage*, *split by engine*, *fit the scaler on train only*, *sliding window* and *validation mimics test*. Ask, then commit: `feat(rul): leakage-safe split, scaling, windows`.

### Task 3: Metrics and Rung A (linear regression), validation only
**Files:** Create `rul/evaluate.py`, `rul/models.py`, `test_rul_evaluate.py`, `test_rul_models.py`

**Interfaces:**
- Produces:
  - `rmse(y_true, y_pred) -> float`.
  - `nasa_score(y_true, y_pred) -> float`, using the standard asymmetric scoring formula (spelled out below).
  - Model protocol (every model has the same 2 methods): `fit(train_df: pd.DataFrame, features: list[str]) -> None` and `predict(df: pd.DataFrame) -> np.ndarray`. The input df is already scaled and has full history per unit. The output is a float per row in df order.
  - `class LinearRUL`: scikit-learn `LinearRegression` on the current row's features, with target `rul_true`.

- [ ] **Step 1: Write the failing tests:**
  - `test_rmse_known_value`: `rmse([0, 0], [3, 4]) ≈ 3.5355`.
  - `test_nasa_score_penalizes_late_more`: d = pred − true. `nasa_score([50], [60]) > nasa_score([50], [40])`, and `nasa_score([50], [50]) == 0`.
  - `test_linear_smoke`: fitting on 2 train units gives predictions of length == rows and all finite.
- [ ] **Step 2:** Run them and verify they FAIL.
- [ ] **Step 3:** Implement. `nasa_score = Σ (exp(-d/13) − 1 if d < 0 else exp(d/10) − 1)`.
- [ ] **Step 4:** Run the tests. Expected: 3 passed.
- [ ] **Step 5:** Add LEARNING.md rows for *baseline*, *RMSE* and *asymmetric score*. Ask, then commit: `feat(rul): metrics and linear baseline`.

### Task 4: Rung B (trees on window features), validation only
**Files:** Modify `rul/models.py`, `test_rul_models.py`

**Interfaces:**
- Produces: `class TreesRUL`, following the same protocol. Its features per row: for each feature, the mean and the slope (least squares vs cycle) over the last `WINDOW` cycles, using `make_windows`. The builder chooses random forest or gradient boosting by validation RMSE. Records the choice and the reason in the class docstring. `random_state=SEED`.

- [ ] **Step 1:** Failing test `test_trees_smoke`: same check as the linear smoke test.
- [ ] **Step 2:** Run it and verify it FAILS.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run it. Expected: PASS.
- [ ] **Step 5:** Add LEARNING.md rows for *feature engineering* and *random forest / boosting*. Ask, then commit: `feat(rul): tree model on window features`.

### Task 5: Rung C (LSTM), validation only
**Files:** Modify `rul/models.py`, `test_rul_models.py`

**Interfaces:**
- Produces: `class LSTMRUL(epochs: int = <builder>, hidden: int = <builder>, lr: float = <builder>)`, following the same protocol. Input: `make_windows` output. Output: a linear head to 1 value. Uses `torch.manual_seed(SEED)` and runs on CPU, with MPS optional. Early stopping uses the validation cut-off RMSE, passed in via the optional `fit(..., val_df=None)` argument.

- [ ] **Step 1:** Failing test `test_lstm_smoke`: `LSTMRUL(epochs=1)` on 2 units gives finite predictions of the right length, in under 30 s.
- [ ] **Step 2:** Run it and verify it FAILS.
- [ ] **Step 3:** Implement. Keep the training loop explicit and short (forward, loss, backward, step), with no Lightning or other framework.
- [ ] **Step 4:** Run it. Expected: PASS.
- [ ] **Step 5:** Add LEARNING.md rows for *LSTM*, *early stopping* and *seeds and reproducibility*. Ask, then commit: `feat(rul): LSTM model`.

### Task 6: Training entry point, freeze, and one-time test scoring
**Files:** Create `rul/train.py`, `test_rul_train.py`, `reports/rul_results.md`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `python -m rul.train [--quick]`. It loads, labels, splits, selects features, scales, fits all 3 models on the train engines, and scores them on the val cut-offs. Then, **only after all three are fitted**, it scores each model on the test set: the prediction at each test unit's last observed row vs `RUL_FD001`. It reports RMSE against the capped truth (`min(true, 125)`), against the uncapped truth, and the NASA score.
  - It writes `reports/rul_results.md`: a table of rungs × {val RMSE, test RMSE capped, test RMSE uncapped, test NASA score}, plus the date, seeds, features and library versions.
  - It saves the model weights to `models/`.
  - `--quick` uses 4 train units, 2 val units and 1 epoch, writes into a temp dir, and is for tests only.

- [ ] **Step 1:** Failing test `test_train_quick_writes_report(tmp_path)`: running with `--quick --out tmp_path` creates a report containing `| linear |`, `| trees |` and `| lstm |`.
- [ ] **Step 2:** Run it and verify it FAILS.
- [ ] **Step 3:** Implement. Test scoring happens in one function, `score_on_test(models, ...)`, called exactly once at the end of `main()`.
- [ ] **Step 4:** Run the quick test. Expected: PASS. Then do the full run: `$ML_PY -m rul.train`, which finishes in a few minutes on CPU, and the report has 3 filled rows.
- [ ] **Step 5:** Report the numbers to Claude. **Don't re-tune after seeing the test scores.** Add LEARNING.md rows for *holdout used once* and *capped vs uncapped RMSE*. Ask, then commit: `feat(rul): training pipeline and test results`.

### Task 7: Predictions CSV
**Files:** Modify `rul/train.py`, `test_rul_train.py`. Create `data/predictions_FD001.csv`.

**Interfaces:**
- Produces: `write_predictions(df: pd.DataFrame, preds: dict[str, np.ndarray], path: Path) -> None`. Columns: `unit, cycle, split, rul_true, rul_linear, rul_trees, rul_lstm`, one row per row of `train_FD001.txt`. `split` is `train` or `val`. Predictions are clipped to [0, 125] and rounded to int. Called by `main()`.

- [ ] **Step 1:** Failing tests:
  - `test_predictions_clipped_and_rounded`: inputs `[-3.2, 130.7, 42.5]` produce `[0, 125, 42]` (`np.rint`, half-to-even), dtype int.
  - `test_predictions_cover_every_row`: a quick run gives a row count equal to the input rows, with no duplicate (unit, cycle).
- [ ] **Step 2:** Run them and verify they FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests and verify they PASS. Rerun the full training run, so the CSV comes from the frozen models (seeded, same results).
- [ ] **Step 5:** Ask, then commit the CSV and the code: `feat(rul): per-cycle predictions file`.

### Task 8: App reads predictions
**Files:** Modify `app.py`, `test_app.py`

**Interfaces:**
- Produces:
  - `create_app(predictions_path: Path | None = <data/predictions_FD001.csv>)`. Existing calls to `create_app()` keep working.
  - If the file exists, the app loads `unit, cycle, split, rul_lstm` at startup. Duplicate (unit, cycle) raises `ValueError` at startup.
  - `/live` and `/cycle` readings gain `rul_pred: int` and `split: "train"|"val"` when there's a matching valid row. Otherwise both keys are absent.
  - The app uses pandas only; no torch or sklearn import.

- [ ] **Step 1:** Failing tests, using a small CSV written to `tmp_path`:
  - `test_live_includes_rul_and_split`
  - `test_cycle_includes_rul_and_split`
  - `test_live_without_predictions_file`: a nonexistent path makes readings lack `rul_pred`, and all existing assertions still hold.
  - `test_live_missing_row_omits_rul`
  - `test_duplicate_prediction_rows_raise`
- [ ] **Step 2:** Run them and verify they FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run all the app tests with `.venv/bin/python`. Expected: all pass.
- [ ] **Step 5:** Add a LEARNING.md row for *offline vs live inference*. Ask, then commit: `feat(app): serve RUL predictions`.

### Task 9: Dashboard shows the estimate and the badge
**Files:** Modify `templates/index.html`, `test_dashboard.js`

**Interfaces:**
- Consumes: the reading fields `rul_pred` and `split` from Task 8.
- Produces:
  - Per panel, an element `[data-rul]` showing `Est. ~${rul_pred} cycles left`, updated each reading.
  - A badge `[data-split]` with the text `seen in training` (split = train) or `validation (unseen)` (split = val).
  - Both stay hidden when the field is absent.

- [ ] **Step 1:** Failing JS tests:
  - `rul text and badge render from readings`
  - `rul elements stay hidden without rul_pred`
- [ ] **Step 2:** Run `node --test test_dashboard.js` and verify they FAIL.
- [ ] **Step 3:** Implement, inside the existing `updateReading` function.
- [ ] **Step 4:** Run all the tests (Python and JS) and verify they pass. Then run the app and check it in the browser.
- [ ] **Step 5:** Ask, then commit: `feat(dashboard): show RUL estimate and split badge`.
