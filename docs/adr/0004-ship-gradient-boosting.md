# Ship gradient boosting

On 2026-11-21, we chose gradient boosting for the dashboard before scoring the official test set. It was simpler, had much steadier validation error across seeds, and did not require PyTorch. [Decision log](../superpowers/specs/2026-11-21-rul-prediction-design.md#decision-log)

## Considered Options

- **LSTM.** Its mean validation RMSE was 13.76 cycles versus 13.96 for boosting, a gap within the LSTM's 0.55-cycle spread across seeds. [Experiments](../../experiments.md#2026-11-21--lstm-hidden-size-on-validation-cutoffs)
