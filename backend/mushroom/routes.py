"""Version-one JSON API routes for sensors, bags, alerts, and exports."""

from __future__ import annotations

import csv
import hmac
import io
import logging
import re
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, Response, jsonify, request, stream_with_context

from .security import clean_text, finite_number

api = Blueprint("monitoring_api", __name__)
LOGGER = logging.getLogger(__name__)
BAG_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _services() -> tuple[Any, Any, Any]:
    """Get dependencies attached to Flask without module-level application state."""
    from flask import current_app

    ext = current_app.extensions["mushroom"]
    return ext["db"], ext["settings"], ext["inference"]


def _error(message: str, status: int) -> tuple[Any, int]:
    """Return the API's consistent JSON error shape."""
    return jsonify({"error": message}), status


def _limit(default: int = 100) -> int | None:
    """Parse a bounded list size from query parameters."""
    value = request.args.get("limit")
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if 1 <= parsed <= 500 else None


def _now() -> str:
    """Return an explicit UTC ISO-8601 timestamp."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _valid_bag_id(value: Any) -> str | None:
    """Restrict externally supplied bag IDs before using them as database keys."""
    cleaned = clean_text(value, 64)
    return cleaned if cleaned and BAG_ID_RE.fullmatch(cleaned) else None


def _record_filters(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter records by room and timestamp without trusting query strings."""
    room = request.args.get("room")
    if room is not None:
        room = clean_text(room, 20)
        if room is None:
            return []
        records = [record for record in records if record.get("room") == room]
    since = request.args.get("since")
    if since:
        try:
            parsed_since = _parse_utc(since)
        except ValueError:
            return []
        records = [
            record
            for record in records
            if _timestamp_or_oldest(record.get("timestamp")) >= parsed_since
        ]
    return records


def _timestamp_or_oldest(value: Any) -> datetime:
    """Parse an ISO timestamp or use the UTC epoch for malformed stored data."""
    try:
        return _parse_utc(str(value))
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, UTC)


def _parse_utc(value: str) -> datetime:
    """Parse ISO-8601 text and consistently treat a missing offset as UTC."""
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@api.post("/sensor")
def sensor() -> Any:
    """Validate and store one environmental reading, then raise threshold alerts."""
    database, _settings, _inference = _services()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Send a JSON object containing temperature and humidity.", 400)
    temperature = data.get("temperature")
    humidity = data.get("humidity")
    if not finite_number(temperature) or not -40 <= temperature <= 85:
        return _error("Temperature must be a number between -40 and 85 °C.", 400)
    if not finite_number(humidity) or not 0 <= humidity <= 100:
        return _error("Humidity must be a number between 0 and 100%.", 400)
    synthetic = data.get("synthetic", False)
    if not isinstance(synthetic, bool):
        return _error("The synthetic marker must be true or false.", 400)
    room = clean_text(data.get("room", "Room 1"), 20)
    device_id = clean_text(data.get("device_id", "unknown"), 64)
    if room is None or device_id is None or any(char in room for char in ".$#[]/"):
        return _error("Room and device names must be short, plain text.", 400)
    timestamp = _now()
    reading = {
        "temperature": float(temperature),
        "humidity": float(humidity),
        "room": room,
        "device_id": device_id,
        "timestamp": timestamp,
    }
    if synthetic:
        reading["synthetic"] = True
    record = {"temp": reading["temperature"], "hum": reading["humidity"], **reading}
    try:
        record_key = database.new_key("records")
        alerts = current_app_alert_engine().process_reading(
            reading, f"records/{record_key}", record
        )
    except Exception as exc:  # noqa: BLE001 - database SDK errors vary; keep them out of responses.
        LOGGER.error("Sensor transaction failed (%s)", type(exc).__name__)
        return _error(
            "The reading could not be saved. Check the database connection and try again.",
            503,
        )
    return jsonify(
        {
            "status": "received",
            "timestamp": timestamp,
            "alerts_raised": [item.get("id") for item in alerts],
        }
    )


def current_app_alert_engine() -> Any:
    """Fetch the configured alert engine from the Flask app extensions."""
    from flask import current_app

    return current_app.extensions["mushroom"]["alerts"]


def current_app_notifier() -> Any:
    """Fetch the configured notification service from Flask extensions."""
    from flask import current_app

    return current_app.extensions["mushroom"]["notifier"]


@api.post("/predict")
def predict() -> Any:
    """Validate an uploaded mushroom-bag image and return a model result."""
    database, settings, inference = _services()
    if not inference.loaded:
        return _error(
            "Photo checks are unavailable until a trained model is installed.", 503
        )
    if request.mimetype != "multipart/form-data":
        return _error("Upload a JPEG, PNG, or WebP photo.", 415)
    uploaded = request.files.get("image")
    if uploaded is None:
        return _error("Choose a photo to check.", 400)
    if uploaded.mimetype not in IMAGE_TYPES:
        return _error("Choose a JPEG, PNG, or WebP photo.", 415)
    image_bytes = uploaded.stream.read(settings.max_upload_bytes + 1)
    if len(image_bytes) > settings.max_upload_bytes:
        return _error("That photo is too large. Choose one under 8 MB.", 413)
    if not _magic_matches(uploaded.mimetype, image_bytes):
        return _error("The file contents do not match the selected image type.", 415)
    supplied_bag_id = request.form.get("bag_id")
    bag_id = (
        _valid_bag_id(supplied_bag_id)
        if supplied_bag_id
        else f"bag-{datetime.now(UTC):%Y%m%d%H%M%S}"
    )
    if bag_id is None:
        return _error(
            "Bag ID may use letters, numbers, hyphens, or underscores (up to 64 characters).",
            400,
        )
    room = clean_text(request.form.get("room", "Room 1"), 20)
    if room is None:
        return _error("Room name must be 20 characters or fewer.", 400)
    try:
        result = inference.predict(image_bytes)
    except ValueError as exc:
        return _error(str(exc), 400)
    except RuntimeError:
        return _error(
            "Photo checks are unavailable until a trained model is installed.", 503
        )
    timestamp = _now()
    bag = {"id": bag_id, "room": room, "timestamp": timestamp, **result}
    try:
        history_key = database.new_key(f"bag_history/{bag_id}")
        current_app_alert_engine().process_prediction(
            bag, f"bag_history/{bag_id}/{history_key}"
        )
    except Exception as exc:  # noqa: BLE001 - database SDK errors vary; keep them out of responses.
        LOGGER.error("Bag result transaction failed (%s)", type(exc).__name__)
        return _error(
            "The photo result could not be saved. Check the database connection and try again.",
            503,
        )
    return jsonify({"bag_id": bag_id, **result, "timestamp": timestamp})


def _magic_matches(mime_type: str, content: bytes) -> bool:
    """Check basic file signatures before image decoding."""
    if mime_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/webp":
        return (
            len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
        )
    return False


@api.post("/alert")
def manual_alert() -> Any:
    """Accept a short, validated message from an external system."""
    _database, _settings, _inference = _services()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Send a JSON object with a message.", 400)
    message = clean_text(data.get("message"), 500)
    if not message:
        return _error(
            "Alert message is required and must be 500 characters or fewer.", 400
        )
    level = data.get("level", "med")
    if level not in {"high", "med", "low"}:
        return _error("Alert level must be high, med, or low.", 400)
    alert_type = clean_text(data.get("type", "manual"), 40)
    location = clean_text(data.get("location", "Farm"), 80)
    if alert_type is None or location is None:
        return _error("Alert type and location must be short plain text.", 400)
    alert = {
        "type": alert_type,
        "message": message,
        "location": location,
        "level": level,
        "status": "open",
        "timestamp": _now(),
        "notified": False,
    }
    try:
        queued = current_app_alert_engine().create_manual_alert(alert)
    except Exception as exc:  # noqa: BLE001 - database exceptions must stay generic.
        LOGGER.error("Manual alert transaction failed (%s)", type(exc).__name__)
        return _error(
            "The alert could not be saved. Check the database connection and try again.",
            503,
        )
    return jsonify(
        {"status": "queued" if queued else "suppressed", "timestamp": _now()}
    )


@api.post("/admin/test-notification")
def test_notification() -> Any:
    """Queue only fixed test text after explicit API-key authentication."""
    _database, settings, _inference = _services()
    supplied = request.headers.get("X-API-Key", "")
    if not settings.api_key or not hmac.compare_digest(supplied, settings.api_key):
        return _error("Set up the API key before sending a notification test.", 401)
    data = request.get_json(silent=True)
    channel = data.get("channel") if isinstance(data, dict) else None
    if channel not in {"email", "sms", "both"}:
        return _error("Choose email, sms, or both for the test.", 400)
    channels = ("email", "sms") if channel == "both" else (channel,)
    results = current_app_notifier().send_test(channels)
    return jsonify({"status": "complete", "channels": results})


@api.get("/sensors/latest")
def latest_sensor() -> Any:
    """Return the most recent reading or an empty object."""
    database, _settings, _inference = _services()
    return jsonify(database.get("sensors/latest") or {})


@api.get("/records")
def records() -> Any:
    """Return a bounded newest-first record list with optional filters."""
    database, _settings, _inference = _services()
    limit = _limit()
    if limit is None:
        return _error("Limit must be between 1 and 500.", 400)
    values = database.query("records", 500)
    room = request.args.get("room")
    if room is not None and clean_text(room, 20) is None:
        return _error("Room filter must be 20 characters or fewer.", 400)
    since = request.args.get("since")
    if since:
        try:
            _parse_utc(since)
        except ValueError:
            return _error("Use an ISO-8601 timestamp for since.", 400)
    filtered = _record_filters(values)
    return jsonify(filtered[:limit])


@api.get("/alerts")
def alerts() -> Any:
    """Return alerts newest first, optionally filtered by known status."""
    database, _settings, _inference = _services()
    limit = _limit()
    if limit is None:
        return _error("Limit must be between 1 and 500.", 400)
    status = request.args.get("status")
    if status is not None and status not in {"open", "review", "resolved"}:
        return _error("Choose open, review, or resolved alert status.", 400)
    results = database.query("alerts", 500)
    if status:
        results = [item for item in results if item.get("status") == status]
    return jsonify(results[:limit])


@api.post("/alerts/<alert_id>/resolve")
def resolve_alert(alert_id: str) -> Any:
    """Mark a known alert resolved without accepting arbitrary field updates."""
    database, _settings, _inference = _services()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", alert_id):
        return _error("Alert ID is invalid.", 400)
    alert = database.get(f"alerts/{alert_id}")
    if not isinstance(alert, dict) or not alert:
        return _error("Alert was not found.", 404)
    alert["status"] = "resolved"
    alert["resolved_at"] = _now()
    database.set(f"alerts/{alert_id}", alert)
    return jsonify({"status": "resolved", "id": alert_id})


@api.get("/bags")
def bags() -> Any:
    """Return current bag summaries."""
    database, _settings, _inference = _services()
    values = database.get("bags") or {}
    results = list(values.values()) if isinstance(values, dict) else []
    results.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
    return jsonify(results[:500])


@api.get("/bags/<bag_id>/history")
def bag_history(bag_id: str) -> Any:
    """Return a single bag's predictions in newest-first order."""
    database, _settings, _inference = _services()
    if not BAG_ID_RE.fullmatch(bag_id):
        return _error("Bag ID is invalid.", 400)
    limit = _limit()
    if limit is None:
        return _error("Limit must be between 1 and 500.", 400)
    return jsonify(database.query(f"bag_history/{bag_id}", limit))


@api.get("/stats/summary")
def summary() -> Any:
    """Calculate descriptive environmental and bag counts for a bounded period."""
    database, _settings, _inference = _services()
    try:
        hours = int(request.args.get("hours", "24"))
    except ValueError:
        return _error("Hours must be a whole number between 1 and 720.", 400)
    if not 1 <= hours <= 720:
        return _error("Hours must be a whole number between 1 and 720.", 400)
    cutoff = datetime.now(UTC).timestamp() - hours * 3600
    values = [
        record
        for record in database.query("records", 500)
        if _timestamp_or_oldest(record.get("timestamp")).timestamp() >= cutoff
    ]
    temps = [
        float(row.get("temp", row.get("temperature")))
        for row in values
        if finite_number(row.get("temp", row.get("temperature")))
    ]
    hums = [
        float(row.get("hum", row.get("humidity")))
        for row in values
        if finite_number(row.get("hum", row.get("humidity")))
    ]
    bags_data = database.get("bags") or {}
    bag_values = list(bags_data.values()) if isinstance(bags_data, dict) else []
    statuses = {
        status: sum(1 for bag in bag_values if bag.get("status") == status)
        for status in ("healthy", "suspect", "contaminated")
    }
    alert_values = database.query("alerts", 500)
    types: dict[str, int] = {}
    for alert in alert_values:
        types[alert.get("type", "other")] = types.get(alert.get("type", "other"), 0) + 1
    return jsonify(
        {
            "hours": hours,
            "temperature": _stats(temps),
            "humidity": _stats(hums),
            "alerts_by_type": types,
            "bags_by_status": statuses,
        }
    )


def _stats(values: list[float]) -> dict[str, float | None]:
    """Return min/average/max or nulls when no sensor data is available."""
    if not values:
        return {"min": None, "avg": None, "max": None}
    return {
        "min": min(values),
        "avg": round(sum(values) / len(values), 2),
        "max": max(values),
    }


@api.get("/records/export.csv")
def export_records() -> Response:
    """Stream bounded record data as a CSV download."""
    database, _settings, _inference = _services()
    rows = _record_filters(database.query("records", 500))

    @stream_with_context
    def generate() -> Any:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["timestamp", "room", "device_id", "temperature_c", "humidity_percent"]
        )
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        for row in rows:
            writer.writerow(
                [
                    row.get("timestamp", ""),
                    row.get("room", ""),
                    row.get("device_id", ""),
                    row.get("temp", row.get("temperature", "")),
                    row.get("hum", row.get("humidity", "")),
                ]
            )
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=mushroom-records.csv"},
    )
