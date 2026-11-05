# V0 spec

Input lines look like:

```
2026-11-04T10:00:00 press-01 temp 71.5
2026-11-04T10:00:05 press-01 temp 98.2
2026-11-04T10:00:05 conveyor-03 vibration 0.42
2026-11-04T10:00:10 conveyor-03 vibration ERR
garbage line
```

Write `summarize(lines, limits)`.
- `lines`: a list of strings, one per log line
- `limits`: maps a sensor type to its maximum allowed value,
  e.g. `{"temp": 90.0, "vibration": 1.0}`

Return, per machine and sensor type:
- the number of readings
- the number over the limit
- the min, max and average of the valid readings

Plus a `skipped` count overall.

How to treat ERR and unknown sensor types is a design decision:
write it down in the README.

Write at least 4 pytest tests, including the one you think is most
likely to catch a bug.

Rules: no AI. Note time taken, lookups, and where you got stuck.
