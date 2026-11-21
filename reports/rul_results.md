# FD001 remaining useful life results

Shipped model (decided on validation, 2026-11-21): gradient boosting

Frozen FD001 evaluation. Run date 2026-11-21.

- **Seeds:** 42 for the engine split, validation cutoffs, boosting, and LSTM.
- **Split:** 80 training engines, 20 validation engines, 100 validation cutoffs. Window length 30, label cap 125.
- **Features:** op_1, op_2, s_2, s_3, s_4, s_6, s_7, s_8, s_9, s_11, s_12, s_13, s_14, s_15, s_17, s_20, s_21. Feature selection and min-max scaling use training engines only.
- **Versions:** Python 3.14.8, NumPy 2.5.5, pandas 3.1.1, scikit-learn 1.9.1, PyTorch 2.15.0, joblib 1.6.0.

| Rung | Val RMSE (capped) | Val NASA (capped) | Test RMSE (capped) | Test RMSE (uncapped) | Test NASA (uncapped) |
|---|---:|---:|---:|---:|---:|
| linear | 22.7153 | 1250.0584 | 20.8469 | 21.8844 | 1313.9206 |
| trees | 13.9408 | 428.6544 | 13.3666 | 14.6539 | 319.6709 |
| lstm | 13.2922 | 296.0538 | 13.5453 | 14.8237 | 312.2101 |

## Shipped model card

- **Model and data.** Gradient boosting on 30-cycle means and slopes. Trained on 80 simulated NASA C-MAPSS FD001 engines. Validated on 100 cutoffs from 20 separate engines and tested on the last observed cycle of each of the 100 official test engines.
- **Intended use.** A learning demo that displays estimates during historical replay.
- **Metrics.** Validation RMSE 13.9408 cycles and NASA score 428.6544 on capped labels. Test RMSE 13.3666 capped and 14.6539 uncapped, with NASA score 319.6709 against uncapped labels.
- **Limitations.** FD001 simulates one operating condition and one fault mode. Training targets are capped at 125 cycles. The comparison LSTM varied more across seeds and used the validation cutoffs for early stopping.
- **When to avoid it.** Keep it out of real maintenance, safety, or scheduling decisions and predictions for other operating conditions, faults, or engine fleets.
