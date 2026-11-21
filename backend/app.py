"""Local presentation API for the Kenya-context mushroom monitor."""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

try:
    from .database import DemoStore, FirebaseDemoStore, MemoryDemoStore
    from .synthetic_demo_data import SYNTHETIC_SCENARIOS
except ImportError:  # Support direct execution as python backend/app.py.
    from database import DemoStore, FirebaseDemoStore, MemoryDemoStore
    from synthetic_demo_data import SYNTHETIC_SCENARIOS

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "backend" / ".env"
load_dotenv(ENV_FILE)
LOGGER = logging.getLogger(__name__)
THRESHOLDS = {"temperature_min": 22.0, "temperature_max": 26.0, "humidity_min": 80.0, "humidity_max": 90.0}


def _timestamp(value: datetime) -> str:
    """Format a timestamp as UTC ISO-8601 with an explicit offset."""
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _configured_store() -> DemoStore:
    """Choose the local memory store or Firebase demo node from environment settings."""
    backend = os.getenv("DB_BACKEND", "memory").strip().lower()
    if backend == "memory":
        return MemoryDemoStore()
    if backend != "firebase":
        raise ValueError("DB_BACKEND must be either memory or firebase.")

    database_url = os.getenv("FIREBASE_URL", "").strip()
    if not database_url:
        raise ValueError("Add FIREBASE_URL to backend/.env before choosing Firebase mode.")
    credential_setting = Path(os.getenv("FIREBASE_CREDENTIALS", "backend/secrets/serviceAccountKey.json"))
    credential_file = credential_setting if credential_setting.is_absolute() else ROOT / credential_setting
    return FirebaseDemoStore(database_url, credential_file)


def _settings_signature() -> int | None:
    """Return the local configuration modification time for safe live reload."""
    try:
        return ENV_FILE.stat().st_mtime_ns
    except OSError:
        return None


def create_app(store: DemoStore | None = None) -> Flask:
    """Create the local presentation API with a memory or Firebase demo store."""
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    store_state: dict[str, Any] = {
        "store": store or _configured_store(),
        "settings_signature": _settings_signature(),
        "store_error": None,
        "fixed_store": store is not None,
    }

    def current_store() -> DemoStore:
        """Return the currently active storage adapter."""
        return store_state["store"]

    @app.before_request
    def reload_local_database_settings() -> Any:
        """Apply changed local settings so the presenter need not edit code."""
        if store_state["fixed_store"]:
            return None
        signature = _settings_signature()
        if signature == store_state["settings_signature"]:
            return None
        try:
            load_dotenv(ENV_FILE, override=True)
            store_state["store"] = _configured_store()
            store_state["store_error"] = None
        except Exception:  # noqa: BLE001 - provider details must not reach the browser or logs.
            LOGGER.error("Could not apply local database settings")
            store_state["store_error"] = True
        store_state["settings_signature"] = signature
        if store_state["store_error"] and request.path.startswith("/api/") and request.path != "/api/health":
            return jsonify({"error": "Firebase is not ready. Check the local Firebase setup and try again."}), 503
        return None

    @app.get("/")
    def dashboard() -> Any:
        return send_from_directory(ROOT, "index.html")

    @app.get("/health")
    def health() -> Any:
        return jsonify({
            "status": "degraded" if store_state["store_error"] else "ok",
            "mode": f"{current_store().backend_name}_demo",
            "db_backend": current_store().backend_name,
            "model_loaded": False,
            "timezone": "Africa/Nairobi",
        })

    @app.get("/api/dashboard")
    def dashboard_data() -> Any:
        try:
            dashboard = current_store().get_dashboard()
        except Exception:  # noqa: BLE001 - keep provider details out of the API response and logs.
            LOGGER.error("Could not read presentation demo data")
            return jsonify({"error": "Could not read the demo data. Check the Firebase connection and try again."}), 503
        return jsonify({
            "mode": f"{current_store().backend_name}_demo",
            "backend": current_store().backend_name,
            "notice": "Demo data — not connected to farm sensors.",
            "timezone": "Africa/Nairobi",
            "currency": "KES",
            "thresholds": THRESHOLDS,
            **dashboard,
        })

    @app.post("/api/simulate")
    def simulate_reading() -> Any:
        payload = request.get_json(silent=True)
        scenario = payload.get("scenario") if isinstance(payload, dict) else None
        if scenario not in SYNTHETIC_SCENARIOS:
            return jsonify({"error": "Choose a demo reading: normal, warm, or dry."}), 400

        temperature, humidity = SYNTHETIC_SCENARIOS[scenario]
        now = datetime.now(UTC)
        reading = {
            "temperature": temperature,
            "humidity": humidity,
            "room": "Room 1",
            "device_id": "SYNTHETIC-DEMO-SENSOR",
            "timestamp": _timestamp(now),
            "synthetic": True,
        }
        alert = None
        if scenario != "normal":
            is_dry = scenario == "dry"
            alert = {
                "type": "Humidity example" if is_dry else "Temperature example",
                "level": "medium",
                "status": "demo",
                "location": "Room 1",
                "message": (f"Example humidity is {humidity}% (below 80%)." if is_dry else f"Example temperature is {temperature} °C (above 26 °C)."),
                "timestamp": _timestamp(now),
                "synthetic": True,
            }
        try:
            current_store().add_reading(reading, alert)
        except Exception:  # noqa: BLE001 - keep provider details out of the API response and logs.
            LOGGER.error("Could not save synthetic demonstration data")
            return jsonify({"error": "Could not save this example. Check the Firebase setup and try again."}), 503
        return jsonify({"status": "synthetic_demo_reading_added", "reading": reading})

    @app.post("/api/demo/reset")
    def reset_demo() -> Any:
        try:
            current_store().reset()
        except Exception:  # noqa: BLE001 - keep provider details out of the API response and logs.
            LOGGER.error("Could not reset synthetic demonstration data")
            return jsonify({"error": "Could not reset the examples. Check the Firebase setup and try again."}), 503
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
    # Bind to loopback for a safe local presentation demo.
    app.run(host="127.0.0.1", port=5000, debug=False)
