import cProfile
import io
import logging
import platform
import pstats
import random
import subprocess
from pathlib import Path
from statistics import quantiles
from time import perf_counter
from unittest.mock import patch

from app import DATA_DIR, create_app
from loader import load_data


def run(client, cycle_paths, only=None):
    samples = {"/live": [], "/cycle": [], "/": [], "/engines": []}

    def get(group, path):
        started = perf_counter()
        response = client.get(path)
        samples[group].append(((perf_counter() - started) * 1000, response.status_code))
        return response

    if only in (None, "/live"):
        cursors = dict.fromkeys(range(1, 11), 0)
        with patch("app.monotonic", lambda: tick / 2):
            for tick in range(100):
                for unit, after in cursors.items():
                    response = get("/live", f"/api/engine/{unit}/live?after={after}")
                    if response.status_code != 200:
                        continue
                    if rows := response.json["readings"]:
                        cursors[unit] = rows[-1]["cycle"]
    pages = {"/cycle": cycle_paths, "/": ["/"] * 20, "/engines": ["/engines"] * 20}
    for group, paths in pages.items():
        if only in (None, group):
            for path in paths:
                get(group, path)
    return samples


def main():
    cpu = platform.machine()
    if platform.system() == "Darwin":
        hardware = subprocess.getoutput("system_profiler SPHardwareDataType")
        cpu = hardware.partition("Chip: ")[2].partition("\n")[0] or cpu
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    keys = load_data(DATA_DIR / "train_FD001.txt")[["unit", "cycle"]]
    pairs = random.Random(0).sample(list(keys.itertuples(index=False, name=None)), 200)
    paths = [f"/api/engine/{unit}/cycle/{cycle}" for unit, cycle in pairs]
    client = create_app().test_client()
    client.application.logger.handlers[:] = [logging.NullHandler()]
    client.application.logger.propagate = False
    run(client, paths)
    started = perf_counter()
    samples = run(client, paths)
    rate = sum(map(len, samples.values())) / (perf_counter() - started)
    lines = f"""# Latency baseline

Python {platform.python_version()} · {platform.platform()} · CPU {cpu} · app commit `{commit}`. Run `make bench` (`.venv/bin/python -m scripts.bench`).

The in-process Flask test client excludes network and browser time. INFO logging creates records and sends them to a NullHandler.

One uncounted warm-up pass precedes the measured pass. Requests run sequentially. In each pass, engines 1–10 get 100 polls each. The clock advances 500 ms per round, and each cursor starts at zero and moves to the last returned cycle. Each pass also samples 200 valid cycles with seed 0 and loads `/` and `/engines` 20 times each.

| Group | Count | Error rate | p50 (ms) | p95 (ms) | Max (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |""".splitlines()
    p95 = {}
    for group, readings in samples.items():
        times, statuses = zip(*readings)
        cuts = quantiles(times, n=100, method="inclusive")
        p95[group] = cuts[94]
        errors = sum(status >= 400 for status in statuses) / len(statuses)
        lines.append(
            f"| `{group}` | {len(times)} | {errors:.1%} | {cuts[49]:.3f} | {cuts[94]:.3f} | {max(times):.3f} |"
        )
    target = "met" if max(p95["/live"], p95["/cycle"]) < 50 else "missed"
    slowest = max(p95, key=p95.get)
    profile = cProfile.Profile()
    profile.runcall(run, client, paths, slowest)
    output = io.StringIO()
    stats = pstats.Stats(profile, stream=output).strip_dirs()
    stats.sort_stats("tottime").print_stats(8)
    lines.append(
        f"\nOverall throughput was {rate:,.0f} requests/sec. **API p95 < 50 ms: {target}.**"
    )
    lines.append(
        f"\n## Profile of `{slowest}` (highest p95)\n\n```text\n{output.getvalue().strip()}\n```"
    )
    if dashboard := stats.get_stats_profile().func_profiles.get("render_dashboard"):
        lines.append(
            f"\nThe dashboard spent {dashboard.cumtime * 1000:.0f} ms across the profiled requests building the page, including calculating sensor ranges and rendering HTML. The default multi-engine page calculates a range for each of four engines."
        )
    Path("reports/latency.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
