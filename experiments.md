# RUL experiments

## 2026-11-21 · Tree model on validation cutoffs

- **Base commit:** `08591c2d3f7f39e998d1e511a32af296321ff535`, plus Task 4's uncommitted `_window_features` helper.
- **Data version:** `data/train_FD001.txt`, Git blob `d2809918c8b75fa3319714658ae994deb2017a89`.
- **Hypothesis:** Gradient boosting will lower validation RMSE compared with a random forest on the same features.
- **Config:** Python 3.14.8, scikit-learn 1.9.1, NumPy 2.5.5, pandas 3.1.1. Each estimator used 100 trees, maximum depth 5, and remaining library defaults.
- **Repeat:** Use `split_engines` with seed 42. Select features and fit the scaler on the 80 training engines. Use `rul.models._window_features` on both full scaled splits. For each seed below, fit the estimator on the training matrix and its capped `rul_true`. Score unrounded predictions on the same five `validation_cutoffs` per validation engine (seed 42, 100 rows total), against capped `rul_true`.

| Estimator | Seed | RMSE (cycles) | NASA score | Fit (s) |
|---|---:|---:|---:|---:|
| RandomForestRegressor | 42 | 18.8992 | 861.6077 | 6.57 |
| RandomForestRegressor | 43 | 18.9371 | 894.4163 | 6.54 |
| RandomForestRegressor | 44 | 18.8467 | 859.8216 | 6.56 |
| GradientBoostingRegressor | 42 | 13.9408 | 428.6544 | 10.82 |
| GradientBoostingRegressor | 43 | 13.9697 | 429.9872 | 10.81 |
| GradientBoostingRegressor | 44 | 13.9699 | 430.0189 | 10.78 |

| Estimator | RMSE mean ± sample SD | NASA score mean ± sample SD |
|---|---:|---:|
| LinearRUL | 22.7153 | 1250.0584 |
| Random forest | 18.8943 ± 0.0454 | 871.9485 ± 19.4782 |
| Gradient boosting | 13.9601 ± 0.0167 | 429.5535 ± 0.7788 |

**Conclusion:** Use gradient boosting with seed 42. Its mean RMSE was 4.93 cycles lower than the forest's, beyond either model's seed spread. Boosting took about 10.81 seconds per fit versus 6.56 seconds for the forest on this machine.

## 2026-11-21 · LSTM hidden size on validation cutoffs

- **Base commit:** `4995685abe1c6ed275926ebe30fdb30fe83bfd82`, plus Task 5's uncommitted LSTM implementation.
- **Data version:** `data/train_FD001.txt`, Git blob `d2809918c8b75fa3319714658ae994deb2017a89`.
- **Hypothesis:** A 32-unit LSTM will lower validation RMSE compared with a 16-unit LSTM. Hidden size was the only configuration change.
- **Config:** Python 3.14.8, PyTorch 2.15.0, two CPU threads, 30-cycle windows, 256 rows per batch, Adam at 0.003, squared-error loss on targets divided by 125, and up to 20 epochs. Stop after four epochs without lower cutoff RMSE and restore the best weights.
- **Repeat:** Use `split_engines`, `select_features`, and `fit_scaler` as in the tree experiment. Keep both full scaled splits and pass the 20 validation engines as `val_df` to `LSTMRUL.fit`. For each run, set `rul.models.SEED` to the listed seed with `unittest.mock.patch`. Select scores from full validation predictions at the indices returned by `validation_cutoffs(val)` (seed 42). Use capped `rul_true` and unrounded predictions. Wall time includes fitting and full validation prediction.

| Hidden size | Seed | RMSE (cycles) | NASA score | Wall time (s) |
|---:|---:|---:|---:|---:|
| 16 | 42 | 13.2922 | 296.0538 | 4.69 |
| 16 | 43 | 14.3600 | 425.9941 | 2.94 |
| 16 | 44 | 13.6181 | 329.9395 | 3.34 |
| 32 | 42 | 13.7201 | 386.0089 | 4.58 |
| 32 | 43 | 14.7556 | 408.0639 | 3.97 |
| 32 | 44 | 14.1727 | 369.3770 | 3.63 |

| Model | RMSE mean ± sample SD | NASA score mean ± sample SD |
|---|---:|---:|
| LinearRUL | 22.7153 | 1250.0584 |
| Gradient boosting | 13.9601 ± 0.0167 | 429.5535 ± 0.7788 |
| LSTM, 16 hidden units | 13.7568 ± 0.5472 | 350.6625 ± 67.4033 |
| LSTM, 32 hidden units | 14.2161 ± 0.5191 | 387.8166 ± 19.4067 |

**Conclusion:** Use 16 hidden units. That configuration had lower mean RMSE and was smaller. Its 0.20-cycle lead over boosting was within the LSTM's seed spread, so the validation results show no clear RMSE winner. The validation cutoffs also selected the best epoch for each LSTM run. This comparison is for tuning.
