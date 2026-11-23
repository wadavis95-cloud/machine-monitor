import logging
from pathlib import Path
from threading import Lock
from time import monotonic, perf_counter
from urllib.parse import quote

import pandas as pd
from flask import Flask, abort, g, jsonify, render_template, request

from loader import load_data

DATA_DIR = Path(__file__).parent / "data"
logger = logging.getLogger(__name__)


def _load_predictions(path: Path | None):
    """Read saved estimates into a lookup by engine and cycle."""
    if path is None:
        return {}
    try:
        rows = pd.read_csv(
            path, comment="#", usecols=["unit", "cycle", "split", "rul_trees"]
        )
    except FileNotFoundError, pd.errors.EmptyDataError:
        return {}
    if rows.duplicated(["unit", "cycle"]).any():
        raise ValueError("Duplicate prediction rows for the same unit and cycle.")

    # Unreadable values become missing. The export contains whole-cycle estimates.
    rows["rul_trees"] = pd.to_numeric(rows["rul_trees"], errors="coerce")
    predictions = {}
    for row in rows.loc[rows["split"].isin(["train", "val"])].itertuples(index=False):
        estimate = row.rul_trees
        if pd.notna(estimate) and float(estimate).is_integer():
            predictions[row.unit, row.cycle] = {
                "rul_pred": int(estimate),
                "split": row.split,
            }
    return predictions


def create_app(predictions_path: Path | None = DATA_DIR / "predictions_FD001.csv"):
    app = Flask(__name__, static_folder=None)
    app.logger.setLevel(logging.INFO)
    data = load_data(DATA_DIR / "train_FD001.txt")
    predictions = _load_predictions(predictions_path)
    final_cycles = data.groupby("unit")["cycle"].max()
    early_readings = data.loc[data["cycle"].between(1, 30)]
    readings_by_cycle = data.set_index(["unit", "cycle"], drop=False)
    live_started_at = {}
    playback_lock = Lock()

    @app.before_request
    def start_request_timer():
        g.request_started_at = perf_counter()

    @app.after_request
    def log_request(response):
        if request.endpoint != "static":
            logger.info(
                "method=%s path=%s endpoint=%s unit=%s status=%s duration_ms=%.1f",
                request.method,
                quote(request.path),
                request.endpoint or "",
                (request.view_args or {}).get("unit", ""),
                response.status_code,
                (perf_counter() - g.request_started_at) * 1000,
            )
        return response

    def render_dashboard(selected, multi=False):
        try:
            selected = list(dict.fromkeys(int(unit) for unit in selected))
        except ValueError:
            abort(404, description="Engine not found.")
        if any(unit not in final_cycles.index for unit in selected):
            abort(404, description="Engine not found.")

        panels = []
        for unit in selected:
            reference = early_readings.loc[early_readings["unit"] != unit, "s_2"]
            lower, upper = reference.quantile([0.05, 0.95])
            panels.append(
                {
                    "unit": unit,
                    "final_cycle": int(final_cycles.loc[unit]),
                    "band_lower": float(lower),
                    "band_upper": float(upper),
                }
            )

        return render_template(
            "index.html",
            unit=selected[0],
            live=request.args.get("mode") == "live",
            units=final_cycles.index,
            selected=selected,
            panels=panels,
            multi=multi,
        )

    @app.get("/")
    def dashboard():
        return render_dashboard([request.args.get("unit", "1")])

    @app.get("/engines")
    def multi_engine_dashboard():
        return render_dashboard(
            request.args.getlist("unit") or [1, 2, 3, 4], multi=True
        )

    @app.get("/health")
    def health():
        return jsonify(
            status="ok" if predictions else "degraded",
            engines=len(final_cycles),
            predictions_loaded=bool(predictions),
        )

    @app.get("/api/engine/<int:unit>/cycle/<int:cycle>")
    def cycle_reading(unit, cycle):
        try:
            row = readings_by_cycle.loc[(unit, cycle), :].to_dict()
        except KeyError:
            return jsonify({"error": "Reading not found"}), 404
        row["unit"] = unit
        row["cycle"] = cycle
        row.update(predictions.get((unit, cycle), {}))
        return jsonify(row)

    @app.get("/api/engine/<int:unit>/live")
    def live_readings(unit):
        if unit not in final_cycles.index:
            abort(404, description="Engine not found.")
        after = request.args.get("after", "0")
        if not after.isascii() or not after.isdecimal() or len(after) > 10:
            abort(400, description="Invalid cycle cursor.")
        after = int(after)

        # The first viewer starts this engine's clock. Later viewers share it.
        with playback_lock:
            now = monotonic()
            started_at = live_started_at.setdefault(unit, now)
        final_cycle = int(final_cycles.loc[unit])
        available_cycle = min(final_cycle, int((now - started_at) * 2) + 1)
        rows = readings_by_cycle.loc[unit].loc[after + 1 : available_cycle]
        readings = rows.to_dict("records")
        for reading in readings:
            reading.update(predictions.get((unit, reading["cycle"]), {}))
        response = jsonify(readings=readings, done=available_cycle == final_cycle)
        response.headers["Cache-Control"] = "no-store"
        return response

    return app
