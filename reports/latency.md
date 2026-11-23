# Latency baseline

Python 3.14.8 · macOS-27.2-arm64-arm-64bit-Mach-O · CPU Apple M5 Pro · app commit `30f22a31d7469ba25d626c41f46ded20f026dd5f`. Run `make bench` (`.venv/bin/python -m scripts.bench`).

The in-process Flask test client excludes network and browser time. INFO logging creates records and sends them to a NullHandler.

One uncounted warm-up pass precedes the measured pass. Requests run sequentially. In each pass, engines 1–10 get 100 polls each. The clock advances 500 ms per round, and each cursor starts at zero and moves to the last returned cycle. Each pass also samples 200 valid cycles with seed 0 and loads `/` and `/engines` 20 times each.

| Group | Count | Error rate | p50 (ms) | p95 (ms) | Max (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `/live` | 1000 | 0.0% | 0.337 | 0.385 | 0.560 |
| `/cycle` | 200 | 0.0% | 0.108 | 0.117 | 0.247 |
| `/` | 20 | 0.0% | 0.327 | 0.390 | 0.537 |
| `/engines` | 20 | 0.0% | 0.892 | 1.066 | 1.108 |

Overall throughput was 3,119 requests/sec. **API p95 < 50 ms: met.**

## Profile of `/engines` (highest p95)

```text
239543 function calls (236203 primitive calls) in 0.053 seconds

   Ordered by: internal time
   List reduced from 625 to 8 due to restriction <8>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
36980/36580    0.003    0.000    0.004    0.000 {built-in method builtins.isinstance}
     6440    0.002    0.000    0.004    0.000 __init__.py:24(escape)
       80    0.002    0.000    0.002    0.000 {method 'partition' of 'numpy.ndarray' objects}
    16040    0.001    0.000    0.010    0.000 index.html:4(root)
     6440    0.001    0.000    0.002    0.000 __init__.py:122(__new__)
      320    0.001    0.000    0.008    0.000 base.py:484(__new__)
      400    0.001    0.000    0.003    0.000 construction.py:580(sanitize_array)
  400/220    0.001    0.000    0.011    0.000 {method 'join' of 'str' objects}
```

The dashboard spent 47 ms across the profiled requests building the page, including calculating sensor ranges and rendering HTML. The default multi-engine page calculates a range for each of four engines.
