"""Clock-driven alert-engine tests; no threads or live providers are required."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.mushroom.alerts import AlertEngine
from backend.mushroom.config import Settings
from backend.mushroom.db import MemoryDB


class FakeClock:
    """Mutable UTC clock for deterministic cooldown and monitor assertions."""

    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **parts: int) -> None:
        self.value += timedelta(**parts)


def settings() -> Settings:
    """Load normal limits while ensuring no test can enable external services."""
    root = Path(__file__).resolve().parents[2]
    return replace(
        Settings.from_env(root / "backend" / ".env", root),
        db_backend="memory",
        firebase_url="",
        api_key="",
        smtp_user="",
        smtp_password="",
        alert_emails=(),
        twilio_account_sid="",
        twilio_auth_token="",
        twilio_from="",
        alert_phones=(),
        alert_cooldown_seconds=600,
        escalation_minutes=30,
        sensor_stale_minutes=10,
    )


def reading(
    temperature: float = 24, humidity: float = 85, room: str = "Room 1"
) -> dict[str, object]:
    """Build a test-only sensor observation with no farm data."""
    return {
        "temperature": temperature,
        "humidity": humidity,
        "room": room,
        "device_id": "TEST-SENSOR",
    }


def test_boundary_values_are_safe_and_four_directions_raise_once() -> None:
    database = MemoryDB()
    engine = AlertEngine(database, settings())
    assert engine.process_reading(reading(22, 80)) == []
    assert engine.process_reading(reading(26, 90)) == []
    alerts = engine.process_reading(reading(21.9, 79.9))
    assert {alert["type"] for alert in alerts} == {"temperature-low", "humidity-low"}
    assert engine.process_reading(reading(21, 79)) == []
    assert {alert["type"] for alert in database.query("alerts")} == {
        "temperature-low",
        "humidity-low",
    }
    engine.process_reading(reading(27, 91, "Room 2"))
    assert len(database.query("alerts")) == 4


def test_hysteresis_recovery_cooldown_and_restart_persistence() -> None:
    database = MemoryDB()
    clock = FakeClock()
    notified: list[dict[str, object]] = []
    engine = AlertEngine(database, settings(), clock, notified.append)
    first = engine.process_reading(reading(24, 76))
    assert [item["type"] for item in first] == ["humidity-low"]
    restarted = AlertEngine(database, settings(), clock, notified.append)
    assert restarted.process_reading(reading(24, 76)) == []
    assert len(database.query("alerts")) == 1

    assert restarted.process_reading(reading(24, 81.9)) == []
    recovered = restarted.process_reading(reading(24, 82))
    assert recovered[0]["type"] == "humidity-low-recovered"
    assert database.query("alerts")[0]["status"] == "resolved"
    assert len(notified) == 2

    clock.advance(minutes=9, seconds=59)
    assert restarted.process_reading(reading(24, 76)) == []
    clock.advance(seconds=2)
    second = restarted.process_reading(reading(24, 76))
    assert second[0]["type"] == "humidity-low"
    assert len(database.query("alerts")) == 3


def test_escalation_stale_alert_recovery_and_single_monitor() -> None:
    database = MemoryDB()
    clock = FakeClock()
    notifications: list[dict[str, object]] = []
    engine = AlertEngine(database, settings(), clock, notifications.append)
    engine.process_reading(reading(24, 76))

    clock.advance(minutes=15)
    engine.process_reading(reading(24, 76))
    clock.advance(minutes=15)
    engine.process_reading(reading(24, 76))
    clock.advance(minutes=1)
    escalated = engine.check_once()
    assert sum(item.get("escalated") is True for item in escalated) == 1
    assert engine.check_once() == []
    assert database.query("alerts")[0]["level"] == "high"

    clock.advance(minutes=10)
    offline = engine.check_once()
    assert [item["type"] for item in offline] == ["sensor-offline"]
    assert engine.check_once() == []
    engine.process_reading(reading(24, 85))
    assert any(item["type"] == "sensor-online" for item in notifications)
    assert database.get("meta/state")["sensor_offline"] is None

    assert engine.start_monitor(interval_seconds=0.05) is True
    duplicate_engine = AlertEngine(database, settings(), clock)
    assert duplicate_engine.start_monitor(interval_seconds=0.05) is False
    engine.stop_monitor()
    assert engine.monitor_running is False


def test_corrupt_state_is_repaired_and_contamination_transitions_dedupe() -> None:
    database = MemoryDB()
    database.set("meta/state", ["broken", "document"])
    engine = AlertEngine(database, settings(), FakeClock())
    bag = {"id": "bag-01", "status": "suspect", "room": "Room 1", "confidence": 0.65}
    assert len(engine.process_prediction(bag)) == 1
    assert engine.process_prediction(bag) == []
    contaminated = engine.process_prediction({**bag, "status": "contaminated"})
    assert contaminated[0]["level"] == "high"
    assert len(database.query("alerts")) == 2
    recovery = engine.process_prediction({**bag, "status": "healthy"})
    assert recovery[0]["type"] == "contamination-recovered"
    assert len(database.query("alerts")) == 3
    assert sum(item["status"] == "resolved" for item in database.query("alerts")) == 3
    assert isinstance(database.get("meta/state"), dict)


def test_bad_nested_state_documents_are_tolerated() -> None:
    database = MemoryDB()
    database.set(
        "meta/state",
        {
            "alert_state": "bad",
            "alert_cooldowns": [],
            "bag_alert_state": False,
            "sensor_offline": "bad",
        },
    )
    engine = AlertEngine(database, settings(), FakeClock())
    assert engine.process_reading(reading(24, 85)) == []
    stored = database.get("meta/state")
    assert stored["alert_state"] == {}
    assert stored["alert_cooldowns"] == {}
    assert stored["bag_alert_state"] == {}
