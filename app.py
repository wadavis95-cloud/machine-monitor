import logging
from pathlib import Path
from threading import Lock
from time import monotonic, perf_counter
from urllib.parse import quote

from flask import Flask, abort, g, jsonify, render_template, request

from assistant.eam import load_predictions
from assistant.flags import t24_band
from assistant.routes import assistant_routes
from loader import load_data

DATA_DIR = Path(__file__).parent / "data"
logger = logging.getLogger(__name__)


def create_app(
    predictions_path: Path | None = DATA_DIR / "predictions_FD001.csv",
    eam_path: Path | None = DATA_DIR / "eam.sqlite",
    chat_model_factory=None,
):
    app = Flask(__name__, static_folder=None)
    app.logger.setLevel(logging.INFO)
    app.config.update(
        EAM_PATH=eam_path,
        ASSISTANT_DATA_DIR=DATA_DIR,
        CHAT_MODEL_FACTORY=chat_model_factory,
    )
    app.extensions["assistant_runs"] = ({}, Lock())
    app.register_blueprint(assistant_routes)
    data = load_data(DATA_DIR / "train_FD001.txt")
    predictions = load_predictions(predictions_path)
    final_cycles = data.groupby("unit")["cycle"].max()
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
            lower, upper = t24_band(data, unit)
            panels.append(
                {
                    "unit": unit,
                    "final_cycle": int(final_cycles.loc[unit]),
                    "band_lower": lower,
                    "band_upper": upper,
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
