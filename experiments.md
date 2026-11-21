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
