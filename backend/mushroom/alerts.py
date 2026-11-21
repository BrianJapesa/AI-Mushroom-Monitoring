"""Threshold alerts with hysteresis and persistent active state."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Any

from .db import Database


class AlertEngine:
    """Create a single alert per excursion and resolve it only after recovery."""

    def __init__(self, database: Database, settings: Any, clock: Any = None) -> None:
        self.database = database
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(UTC))
        self._lock = Lock()

    def process_reading(self, reading: dict[str, Any]) -> list[dict[str, Any]]:
        """Check all four environmental bounds and apply recovery margins."""
        created: list[dict[str, Any]] = []
        with self._lock:
            states = self.database.get("meta/state/alert_state") or {}
            checks = (
                (
                    "temperature-low",
                    "temperature",
                    reading["temperature"],
                    self.settings.temp_min,
                    "low",
                    "Temperature is below the room target.",
                ),
                (
                    "temperature-high",
                    "temperature",
                    reading["temperature"],
                    self.settings.temp_max,
                    "high",
                    "Temperature is above the room target.",
                ),
                (
                    "humidity-low",
                    "humidity",
                    reading["humidity"],
                    self.settings.hum_min,
                    "low",
                    "Humidity is below the room target.",
                ),
                (
                    "humidity-high",
                    "humidity",
                    reading["humidity"],
                    self.settings.hum_max,
                    "high",
                    "Humidity is above the room target.",
                ),
            )
            for key, metric, value, threshold, direction, message in checks:
                scoped_key = f"{key}|{reading['room']}"
                active = states.get(scoped_key)
                outside = value < threshold if direction == "low" else value > threshold
                margin = (
                    self.settings.recovery_margin_temp
                    if metric == "temperature"
                    else self.settings.recovery_margin_humidity
                )
                recovered = (
                    value >= threshold + margin
                    if direction == "low"
                    else value <= threshold - margin
                )
                if active and recovered:
                    recovery = self._make_alert(
                        reading,
                        key,
                        f"{metric.title()} is back in its safe range.",
                        "low",
                        "resolved",
                    )
                    self.database.push("alerts", recovery)
                    created.append(recovery)
                    states.pop(scoped_key, None)
                elif not active and outside:
                    alert = self._make_alert(reading, key, message, "med", "open")
                    alert["value"] = value
                    alert["threshold"] = threshold
                    alert["id"] = self.database.push("alerts", alert)
                    created.append(alert)
                    states[scoped_key] = {
                        "alert_id": alert["id"],
                        "raised_at": alert["timestamp"],
                        "level": "med",
                    }
            self.database.set("meta/state/alert_state", states)
        return created

    def _make_alert(
        self, reading: dict[str, Any], kind: str, message: str, level: str, status: str
    ) -> dict[str, Any]:
        """Build a compact alert record with a timezone-aware UTC timestamp."""
        now = self.clock().astimezone(UTC).isoformat(timespec="seconds")
        return {
            "type": kind,
            "message": message,
            "location": reading["room"],
            "level": level,
            "status": status,
            "timestamp": now,
            "notified": False,
        }
