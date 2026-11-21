"""Offline prototype API for the mushroom monitoring dashboard.

The prototype deliberately serves synthetic demonstration records only. It does
not connect to farm sensors, Firebase, notification providers, or an AI model.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

try:
    from .synthetic_demo_data import SYNTHETIC_SCENARIOS, build_synthetic_demo_state
except ImportError:  # Support direct execution as python backend/app.py.
    from synthetic_demo_data import SYNTHETIC_SCENARIOS, build_synthetic_demo_state

ROOT = Path(__file__).resolve().parent.parent
THRESHOLDS = {"temperature_min": 22.0, "temperature_max": 26.0, "humidity_min": 80.0, "humidity_max": 90.0}


def _timestamp(value: datetime) -> str:
    """Format a timestamp as UTC ISO-8601 with an explicit offset."""
    return value.astimezone(UTC).isoformat(timespec="seconds")


def create_app() -> Flask:
    """Create the local-only demo API and its in-memory synthetic state."""
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    state = build_synthetic_demo_state()
    state_lock = Lock()

    @app.get("/")
    def dashboard() -> Any:
        return send_from_directory(ROOT, "index.html")

    @app.get("/health")
    def health() -> Any:
        return jsonify({"status": "ok", "mode": "synthetic_demo", "db_backend": "memory", "model_loaded": False, "timezone": "Africa/Nairobi"})

    @app.get("/api/dashboard")
    def dashboard_data() -> Any:
        with state_lock:
            return jsonify({
                "mode": "synthetic_demo",
                "notice": "Demo data — not connected to your farm.",
                "timezone": "Africa/Nairobi",
                "currency": "KES",
                "thresholds": THRESHOLDS,
                "latest": state["latest"],
                "records": state["records"],
                "alerts": state["alerts"],
                "bags": state["bags"],
            })

    @app.post("/api/simulate")
    def simulate_reading() -> Any:
        payload = request.get_json(silent=True)
        scenario = payload.get("scenario") if isinstance(payload, dict) else None
        if scenario not in SYNTHETIC_SCENARIOS:
            return jsonify({"error": "Choose a demo reading: normal, warm, or dry."}), 400

        temperature, humidity = SYNTHETIC_SCENARIOS[scenario]
        now = datetime.now(UTC)
        with state_lock:
            state["sequence"] += 1
            reading = {
                "temperature": temperature,
                "humidity": humidity,
                "room": "Room 1",
                "device_id": "SYNTHETIC-DEMO-SENSOR",
                "timestamp": _timestamp(now),
                "synthetic": True,
            }
            state["latest"] = reading
            state["records"].append(reading)
            state["records"] = state["records"][-200:]
            if scenario != "normal":
                is_dry = scenario == "dry"
                alert = {
                    "id": f"SYNTHETIC-DEMO-ALERT-{state['sequence']:03d}",
                    "type": "Humidity example" if is_dry else "Temperature example",
                    "level": "medium",
                    "status": "demo",
                    "location": "Room 1",
                    "message": (f"Example humidity is {humidity}% (below 80%)." if is_dry else f"Example temperature is {temperature} °C (above 26 °C)."),
                    "timestamp": _timestamp(now),
                    "synthetic": True,
                }
                state["alerts"].insert(0, alert)
                state["alerts"] = state["alerts"][:50]
        return jsonify({"status": "synthetic_demo_reading_added", "reading": reading})

    @app.post("/api/demo/reset")
    def reset_demo() -> Any:
        with state_lock:
            state.clear()
            state.update(build_synthetic_demo_state())
        return jsonify({"status": "synthetic_demo_reset"})

    @app.post("/api/predict")
    def predict() -> Any:
        return jsonify({"error": "Photo checks are not active in this prototype. A trained, farm-reviewed model is required."}), 503

    @app.errorhandler(413)
    def too_large(_: Exception) -> Any:
        return jsonify({"error": "That file is too large. Choose a file smaller than 8 MB."}), 413

    return app


app = create_app()


if __name__ == "__main__":
    # Binding to loopback keeps this demonstration available only on this PC.
    app.run(host="127.0.0.1", port=5000, debug=False)
