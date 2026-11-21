# Split training and validation by engine

FD001 provides 100 complete engine histories for training and validation. We assign 80 whole engines to training and 20 to validation so the same engine's readings cannot appear on both sides. Adjacent 30-cycle windows from one engine share 29 readings, so splitting by row could leak near-copies of training examples into validation and make its error look too low. [Design](../superpowers/specs/2026-11-21-rul-prediction-design.md#data) · [Results](../../reports/rul_results.md)
