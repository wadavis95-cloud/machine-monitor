# Machine-Monitor

Machine-Monitor is a learning demo that plays back simulated engine histories. It shows sensor readings, warnings, and an estimate of how many cycles remain before simulated failure.

## Language

**Engine**: One simulated engine with its own operating history.

_Avoid_: unit

**Cycle**: One numbered step in an engine's operating history, with one set of sensor readings.

_Avoid_: operating cycle, time step

**Cursor**: The cycle number of the most recent reading a viewer has received in simulated live mode.

_Avoid_: last-seen position, bookmark

**Replay**: A playback mode that advances through recorded cycles independently for each viewer, who can restart from the beginning.

_Avoid_: playback mode, historical replay

**Simulated live**: A shared playback mode where recorded cycles become available over time at the same pace for everyone watching that engine.

_Avoid_: live, real-time feed

**RUL estimate**: The model's estimate of the number of cycles remaining before simulated failure. RUL stands for remaining useful life.

_Avoid_: RUL prediction, predicted RUL

**Capped target**: The known number of cycles remaining before failure, limited to 125, used as the answer the model learns to predict.

_Avoid_: capped RUL, clipped label

**Training engine**: An engine whose readings and targets are used to fit the model.

_Avoid_: training unit, seen engine

**Validation engine**: An engine held aside from training and used to compare or tune models.

_Avoid_: validation unit, validation test engine

**Validation cutoff**: A selected cycle before a validation engine's failure where the estimate is checked using the history available through that cycle.

_Avoid_: validation checkpoint, validation endpoint

**Official test engine**: An engine in NASA's separate FD001 test set. Its recorded history ends before failure, and its remaining life at the last recorded cycle is used for final scoring.

_Avoid_: test engine, test unit
