# machine-monitor

## V0 decisions

### 1. What counts as a malformed line?
**Decision:** A line is malformed if:
- it doesn't have exactly 4 parts, or
- its value isn't a number, or
- its value is `nan`.

Exception: `ERR` is not malformed. It's handled in question 2.

A malformed line adds 1 to `skipped` and doesn't affect any sensor's
numbers (reading count, over-limit count, min, max or average).


**Why:** To protect the integrity of the data, no guessing or malformed lines will be accepted to prevent false telemetry readings.

Example of a Good line:
```
2026-11-05T07:17:00 press-01 temp 72.1
```
Examples of Bad lines:  
```
2026-11-05T07:17:00 press-01 temp       (too few parts)
2026-11-05T07:17:00 press               (too few parts, cut off)
2026-11-05T07:17:00 press 01 temp 72.1  (too many parts)
```

### 2. What happens with ERR?
**Decision:** Keep the line containing error.

**Why:** It will provide further insight into patterns involving the types of sensors prone to error for troubleshooting.

### 3. What happens with a sensor type not in limits?
**Decision:** An alarm will appear on the dashboard.

**Why:** Engineers and technicians can be made aware of potential issues that can be handled before said equipment causes undesired outcomes.

### 4. Does "over the limit" mean > or >=?
**Decision:** It means greater than.

**Why:** Anything above the desired setpoint or threshold will be shown on the dashboard as an alarm to monitor.

## Future ideas
- Model the plant hierarchy: production line → machine → component → sensor → readings (V2: data modelling)
