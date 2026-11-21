# Fit the scaler on training engines only

The models need a consistent scale for sensor readings. We find each feature's minimum and maximum on the training engines and reuse those ranges for validation and test, so held-out readings cannot influence how the models are trained. [Design](../superpowers/specs/2026-11-21-rul-prediction-design.md#data) · [Experiments](../../experiments.md)
