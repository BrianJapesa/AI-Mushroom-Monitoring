"""Local presentation API for the Kenya-context mushroom monitor."""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

try:
    from .database import DemoStore, FirebaseDemoStore, MemoryDemoStore
    from .mushroom import create_monitoring_app
    from .mushroom.config import Settings
    from .mushroom.db import Database
    from .mushroom.inference import InferenceService
    from .mushroom.notifier import Notifier
    from .mushroom.security import clean_text, finite_number
except ImportError:  # Support direct execution as python backend/app.py.
    from database import DemoStore, FirebaseDemoStore, MemoryDemoStore
    from mushroom import create_monitoring_app
    from mushroom.config import Settings
    from mushroom.db import Database
    from mushroom.inference import InferenceService
    from mushroom.notifier import Notifier
    from mushroom.security import clean_text, finite_number

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "backend" / ".env"
load_dotenv(ENV_FILE)
LOGGER = logging.getLogger(__name__)
THRESHOLDS = {
    "temperature_min": 22.0,
    "temperature_max": 26.0,
    "humidity_min": 80.0,
    "humidity_max": 90.0,
}
DEMO_TARGET_LIMITS = {
    "temperature_min": (-40.0, 84.0),
    "temperature_max": (-39.0, 84.0),
    "humidity_min": (1.0, 99.0),
    "humidity_max": (2.0, 100.0),
}


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
        raise ValueError(
            "Add FIREBASE_URL to backend/.env before choosing Firebase mode."
        )
    credential_setting = Path(
        os.getenv("FIREBASE_CREDENTIALS", "backend/secrets/serviceAccountKey.json")
    )
    credential_file = (
        credential_setting
        if credential_setting.is_absolute()
        else ROOT / credential_setting
    )
    return FirebaseDemoStore(database_url, credential_file)


def _settings_signature() -> int | None:
    """Return the local configuration modification time for safe live reload."""
    try:
        return ENV_FILE.stat().st_mtime_ns
    except OSError:
        return None


def _server_bind_options() -> tuple[str, int]:
    """Choose a loopback-safe local bind unless the hosting platform overrides it."""
    return os.getenv("HOST", "127.0.0.1"), int(os.getenv("PORT", "5000"))


def _validated_demo_thresholds(value: Any) -> dict[str, float] | None:
    """Accept only complete finite target ranges within safe sensor bounds."""
    if not isinstance(value, dict):
        return None
    result: dict[str, float] = {}
    for key, (minimum, maximum) in DEMO_TARGET_LIMITS.items():
        number = value.get(key)
        if not finite_number(number) or not minimum <= number <= maximum:
            return None
        result[key] = float(number)
    if (
        result["temperature_min"] >= result["temperature_max"]
        or result["humidity_min"] >= result["humidity_max"]
    ):
        return None
    return result


class UnavailableDemoStore:
    """Preserve app startup while avoiding fake fallback data on Firebase errors."""

    backend_name = "unavailable"

    @staticmethod
    def _fail(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("Presentation database is not available.")

    get_dashboard = _fail
    add_reading = _fail
    reset = _fail


def create_app(
    store: DemoStore | None = None,
    database: Database | None = None,
    settings: Settings | None = None,
    inference: InferenceService | None = None,
    notifier: Notifier | None = None,
) -> Flask:
    """Create the local presentation API with a memory or Firebase demo store."""
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    runtime_settings = settings or Settings.from_env(ENV_FILE, ROOT)
    store_error = False
    if store is None:
        try:
            active_store = _configured_store()
        except Exception:  # noqa: BLE001 - provider errors must not block app startup.
            LOGGER.error(
                "Presentation database is not ready; dashboard data is unavailable"
            )
            active_store = UnavailableDemoStore()
            store_error = True
    else:
        active_store = store
    store_state: dict[str, Any] = {
        "store": active_store,
        "settings_signature": _settings_signature(),
        "store_error": store_error,
        "fixed_store": store is not None,
    }
    demo_target_lock = Lock()
    demo_targets = dict(THRESHOLDS)
    create_monitoring_app(
        ROOT,
        settings=runtime_settings,
        database=database,
        inference=inference,
        app=app,
        notifier=notifier,
    )

    def current_store() -> DemoStore:
        """Return the currently active storage adapter."""
        return store_state["store"]

    def current_demo_targets() -> dict[str, float]:
        """Return a thread-safe copy of this app's adjustable demo targets."""
        with demo_target_lock:
            return dict(demo_targets)

    def make_alert(
        reading: dict[str, Any], targets: dict[str, float]
    ) -> dict[str, Any] | None:
        """Build a clearly synthetic alert when a demo reading is outside targets."""
        violations = []
        temperature = reading["temperature"]
        humidity = reading["humidity"]
        if temperature < targets["temperature_min"]:
            violations.append(
                f"temperature {temperature:g} °C is below {targets['temperature_min']:g} °C"
            )
        elif temperature > targets["temperature_max"]:
            violations.append(
                f"temperature {temperature:g} °C is above {targets['temperature_max']:g} °C"
            )
        if humidity < targets["humidity_min"]:
            violations.append(
                f"humidity {humidity:g}% is below {targets['humidity_min']:g}%"
            )
        elif humidity > targets["humidity_max"]:
            violations.append(
                f"humidity {humidity:g}% is above {targets['humidity_max']:g}%"
            )
        if not violations:
            return None
        alert_type = (
            "Temperature example"
            if violations[0].startswith("temperature")
            else "Humidity example"
        )
        return {
            "type": alert_type,
            "level": "medium",
            "status": "demo",
            "location": reading["room"],
            "message": "Example reading is outside the saved targets: "
            + "; ".join(violations)
            + ".",
            "timestamp": reading["timestamp"],
            "synthetic": True,
        }

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
        if (
            store_state["store_error"]
            and request.path.startswith("/api/")
            and request.path != "/api/health"
        ):
            return jsonify(
                {
                    "error": "Firebase is not ready. Check the local Firebase setup and try again."
                }
            ), 503
        return None

    @app.get("/")
    def dashboard() -> Any:
        return send_from_directory(ROOT, "index.html")

    @app.get("/health")
    def health() -> Any:
        """Report readiness without exposing local paths or provider errors."""
        ext = app.extensions["mushroom"]
        db = ext["db"]
        try:
            if getattr(db, "name", "") == "firebase":
                db.get("meta/healthcheck")
            connected = getattr(db, "name", "") == "firebase"
            state = db.get("meta/state") or {}
            last_sensor_ts = (
                state.get("last_sensor_ts") if isinstance(state, dict) else None
            )
        except Exception:  # noqa: BLE001 - health data must not leak provider details.
            connected = False
            last_sensor_ts = None
        inference = ext["inference"]
        delivery = ext["notifier"].health()
        return jsonify(
            {
                "status": "degraded"
                if store_state["store_error"]
                or db.name == "unavailable"
                or (db.name == "firebase" and not connected)
                else "ok",
                "version": "1.0.0",
                "mode": f"{current_store().backend_name}_demo",
                "db_backend": db.name,
                "firebase_connected": connected,
                "auth_required": bool(runtime_settings.api_key),
                "sms_enabled": delivery["sms_enabled"],
                "email_enabled": delivery["email_enabled"],
                "email_last_ok_ts": delivery["email_last_ok_ts"],
                "email_last_error_class": delivery["email_last_error_class"],
                "sms_last_ok_ts": delivery["sms_last_ok_ts"],
                "sms_last_error_class": delivery["sms_last_error_class"],
                "notification_failures": delivery["delivery_failures"],
                "notification_queue_size": delivery["queue_size"],
                "last_sensor_ts": last_sensor_ts,
                "alert_monitor_running": ext["alerts"].monitor_running,
                "demo_mode": True,
                "model_loaded": inference.loaded,
                "model_version": inference.version,
                "model_synthetic": inference.synthetic,
                "uptime_s": round(time.monotonic() - ext["started_at"]),
                "timezone": runtime_settings.timezone,
            }
        )

    @app.get("/api/dashboard")
    def dashboard_data() -> Any:
        try:
            dashboard = current_store().get_dashboard()
        except Exception:  # noqa: BLE001 - keep provider details out of the API response and logs.
            LOGGER.error("Could not read presentation demo data")
            return jsonify(
                {
                    "error": "Could not read the demo data. Check the Firebase connection and try again."
                }
            ), 503
        return jsonify(
            {
                "mode": f"{current_store().backend_name}_demo",
                "backend": current_store().backend_name,
                "notice": "Demo data — not connected to farm sensors.",
                "timezone": "Africa/Nairobi",
                "currency": "KES",
                "thresholds": current_demo_targets(),
                **dashboard,
            }
        )

    @app.post("/api/simulate")
    def simulate_reading() -> Any:
        payload = request.get_json(silent=True)
        scenario = payload.get("scenario") if isinstance(payload, dict) else None
        if scenario not in {"normal", "warm", "dry"}:
            return jsonify(
                {"error": "Choose a demo reading: normal, warm, or dry."}
            ), 400

        targets = current_demo_targets()
        temperature = (targets["temperature_min"] + targets["temperature_max"]) / 2
        humidity = (targets["humidity_min"] + targets["humidity_max"]) / 2
        if scenario == "warm":
            temperature = targets["temperature_max"] + 1
        elif scenario == "dry":
            humidity = targets["humidity_min"] - 1
        now = datetime.now(UTC)
        reading = {
            "temperature": temperature,
            "humidity": humidity,
            "room": "Room 1",
            "device_id": "SYNTHETIC-DEMO-SENSOR",
            "timestamp": _timestamp(now),
            "synthetic": True,
        }
        alert = make_alert(reading, targets)
        try:
            current_store().add_reading(reading, alert)
        except Exception:  # noqa: BLE001 - keep provider details out of the API response and logs.
            LOGGER.error("Could not save synthetic demonstration data")
            return jsonify(
                {
                    "error": "Could not save this example. Check the Firebase setup and try again."
                }
            ), 503
        return jsonify({"status": "synthetic_demo_reading_added", "reading": reading})

    @app.post("/api/thresholds")
    def update_demo_thresholds() -> Any:
        """Save adjustable targets for this running demo process."""
        targets = _validated_demo_thresholds(request.get_json(silent=True))
        if targets is None:
            return jsonify(
                {
                    "error": "Enter valid target ranges. Temperature must be -40 to 84 °C and humidity 0 to 100%, with each minimum below its maximum."
                }
            ), 400
        with demo_target_lock:
            demo_targets.clear()
            demo_targets.update(targets)
        return jsonify(
            {"status": "demo_targets_updated", "thresholds": targets, "synthetic": True}
        )

    @app.post("/api/demo/reading")
    def add_custom_demo_reading() -> Any:
        """Add a user-entered synthetic reading to the presentation demo store."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(
                {"error": "Enter a temperature and humidity for the demo reading."}
            ), 400
        temperature, humidity = payload.get("temperature"), payload.get("humidity")
        room = clean_text(payload.get("room", "Room 1"), 30)
        if not finite_number(temperature) or not -40 <= temperature <= 85:
            return jsonify(
                {"error": "Temperature must be a number from -40 to 85 °C."}
            ), 400
        if not finite_number(humidity) or not 0 <= humidity <= 100:
            return jsonify({"error": "Humidity must be a number from 0 to 100%."}), 400
        if room is None:
            return jsonify({"error": "Room name must be 1 to 30 characters."}), 400
        now = datetime.now(UTC)
        reading = {
            "temperature": float(temperature),
            "humidity": float(humidity),
            "room": room,
            "device_id": "SYNTHETIC-DEMO-SENSOR",
            "timestamp": _timestamp(now),
            "synthetic": True,
        }
        alert = make_alert(reading, current_demo_targets())
        try:
            current_store().add_reading(reading, alert)
        except Exception:  # noqa: BLE001 - keep provider details out of the API response and logs.
            LOGGER.error("Could not save synthetic demonstration data")
            return jsonify(
                {
                    "error": "Could not save this example. Check the Firebase setup and try again."
                }
            ), 503
        return jsonify(
            {
                "status": "synthetic_demo_reading_added",
                "reading": reading,
                "alert": alert,
            }
        )

    @app.post("/api/demo/reset")
    def reset_demo() -> Any:
        try:
            current_store().reset()
        except Exception:  # noqa: BLE001 - keep provider details out of the API response and logs.
            LOGGER.error("Could not reset synthetic demonstration data")
            return jsonify(
                {
                    "error": "Could not reset the examples. Check the Firebase setup and try again."
                }
            ), 503
        with demo_target_lock:
            demo_targets.clear()
            demo_targets.update(THRESHOLDS)
        return jsonify({"status": "synthetic_demo_reset"})

    @app.post("/api/predict")
    def predict() -> Any:
        return jsonify(
            {
                "error": "Photo checks are not active in this prototype. A trained, farm-reviewed model is required."
            }
        ), 503

    @app.errorhandler(413)
    def too_large(_: Exception) -> Any:
        return jsonify(
            {"error": "That file is too large. Choose a file smaller than 8 MB."}
        ), 413

    return app


app = create_app()


if __name__ == "__main__":
    # Use a Windows-compatible production server, bound locally by default.
    from waitress import serve

    monitor = app.extensions["mushroom"]["alerts"]
    monitor.start_monitor()
    try:
        host, port = _server_bind_options()
        serve(app, host=host, port=port)
    finally:
        monitor.stop_monitor()
        app.extensions["mushroom"]["notifier"].close()
