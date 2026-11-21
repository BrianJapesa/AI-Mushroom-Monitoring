"""Configuration, demo boundary, logging, retention, and admin-route checks."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app import _server_bind_options, create_app
from backend.database import MemoryDemoStore
from backend.mushroom.config import Settings
from backend.mushroom.db import DatabaseUnavailable, MemoryDB
from backend.mushroom.logging_setup import JsonLogFormatter, PIIMaskingFilter
from backend.mushroom.retention import RetentionJob


def safe_settings(root: Path, **changes: Any) -> Settings:
    """Return a memory configuration with all external delivery disabled."""
    value = Settings.from_env(root / "backend" / ".env", root)
    value = replace(
        value,
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
    )
    return replace(value, **changes)


def test_server_bind_options_default_to_loopback_and_allow_host_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    assert _server_bind_options() == ("127.0.0.1", 5000)
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "10000")
    assert _server_bind_options() == ("0.0.0.0", 10000)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TEMP_MIN", "nan"),
        ("ALERT_COOLDOWN", "not-a-number"),
        ("MIN_CONFIDENCE", "1.1"),
        ("SMTP_SECURITY", "plain"),
        ("SMTP_PORT", "2525"),
        ("ALERT_LANGUAGE", "fr"),
        ("RETENTION_DAYS_RECORDS", "-1"),
    ],
)
def test_invalid_settings_fail_clearly(
    name: str, value: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DB_BACKEND", "memory")
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        Settings.from_env(tmp_path / "missing.env", tmp_path)


def test_database_outage_returns_generic_503_and_request_id() -> None:
    root = Path(__file__).resolve().parents[2]

    class BrokenDB:
        name = "firebase"

        @staticmethod
        def get(*_args: Any, **_kwargs: Any) -> Any:
            raise DatabaseUnavailable("TEST-ONLY-provider-detail")

        set = get
        push = get
        update = get
        delete = get
        query = get
        new_key = get

    app = create_app(
        store=MemoryDemoStore(),
        database=BrokenDB(),  # type: ignore[arg-type]
        settings=safe_settings(root),
    )
    client = app.test_client()
    response = client.get("/records", headers={"X-Request-ID": "request-123"})
    assert response.status_code == 503
    assert response.json == {
        "error": "The database is temporarily unavailable. Try again shortly."
    }
    assert response.headers["X-Request-ID"] == "request-123"
    generated = client.get("/health", headers={"X-Request-ID": "bad request id"})
    assert generated.headers["X-Request-ID"] != "bad request id"


def test_sensor_multi_path_failure_does_not_leave_partial_records(
    caplog: pytest.LogCaptureFixture,
) -> None:
    root = Path(__file__).resolve().parents[2]

    class FailingUpdateDB(MemoryDB):
        @staticmethod
        def update(_values: dict[str, Any]) -> None:
            raise DatabaseUnavailable("TEST-ONLY-provider-detail")

    database = FailingUpdateDB()
    app = create_app(
        store=MemoryDemoStore(), database=database, settings=safe_settings(root)
    )
    caplog.set_level("ERROR")
    response = app.test_client().post(
        "/sensor", json={"temperature": 24, "humidity": 76}
    )

    assert response.status_code == 503
    assert response.json == {
        "error": "The reading could not be saved. Check the database connection and try again."
    }
    assert database.get("sensors/latest") == {}
    assert database.query("records") == []
    assert "Sensor transaction failed (DatabaseUnavailable)" in caplog.text
    assert "TEST-ONLY-provider-detail" not in caplog.text


def test_demo_and_live_storage_are_isolated_and_labelled() -> None:
    root = Path(__file__).resolve().parents[2]
    database = MemoryDB()
    database.set("demo/records/example", {"synthetic": True, "temperature": 999})
    store = MemoryDemoStore()
    app = create_app(store=store, database=database, settings=safe_settings(root))
    client = app.test_client()
    before = client.get("/api/dashboard").json
    assert "demo" in before["mode"]
    assert "Demo data" in before["notice"]
    assert before["latest"]["synthetic"] is True
    assert client.get("/records").json == []

    sensor = client.post(
        "/sensor", json={"temperature": 24, "humidity": 85, "synthetic": True}
    )
    assert sensor.status_code == 200
    assert client.get("/records").json[0]["synthetic"] is True
    assert database.get("demo/records/example")["temperature"] == 999
    after_live = database.query("records")
    client.post("/api/simulate", json={"scenario": "warm"})
    assert database.query("records") == after_live
    assert database.get("demo/records/example")["temperature"] == 999


def test_retention_is_disabled_by_default_and_dry_run_does_not_delete() -> None:
    database = MemoryDB()
    database.set("records/old", {"timestamp": "2020-01-01T00:00:00+00:00"})
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert RetentionJob(database, 0, lambda: now).run() == {
        "enabled": False,
        "candidates": 0,
        "deleted": 0,
    }
    job = RetentionJob(database, 365, lambda: now)
    assert job.run(dry_run=True) == {"enabled": True, "candidates": 1, "deleted": 0}
    assert database.get("records/old")
    assert job.run(dry_run=False) == {"enabled": True, "candidates": 1, "deleted": 1}
    assert database.get("records/old") == {}


def test_log_filter_masks_emails_phones_and_secrets() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        "test.py",
        1,
        "recipient=%s phone=%s API_KEY=%s",
        ("staff@example.test", "+254700000002", "TEST-ONLY-KEY"),
        None,
    )
    assert PIIMaskingFilter().filter(record)
    assert "staff@example.test" not in record.getMessage()
    assert "+254700000002" not in record.getMessage()
    assert "TEST-ONLY-KEY" not in record.getMessage()
    formatted = JsonLogFormatter().format(record)
    assert json.loads(formatted)["request_id"] == "-"


class FakeTestNotifier:
    """Notifier response stub for admin-route auth tests."""

    @staticmethod
    def enqueue(_alert: dict[str, Any]) -> bool:
        return True

    def send_test(self, channels: tuple[str, ...]) -> dict[str, Any]:
        return {
            channel: {"success": True, "message": "Test sent."} for channel in channels
        }

    def health(self) -> dict[str, Any]:
        return {
            "email_enabled": False,
            "sms_enabled": False,
            "email_last_ok_ts": None,
            "email_last_error_class": None,
            "sms_last_ok_ts": None,
            "sms_last_error_class": None,
            "delivery_failures": {"email": 0, "sms": 0},
            "queue_size": 0,
        }


def test_admin_test_notification_requires_key_and_valid_channel() -> None:
    root = Path(__file__).resolve().parents[2]
    settings = safe_settings(root, api_key="TEST-ONLY-ADMIN-KEY")
    app = create_app(
        store=MemoryDemoStore(),
        database=MemoryDB(),
        settings=settings,
        notifier=FakeTestNotifier(),
    )  # type: ignore[arg-type]
    client = app.test_client()
    assert (
        client.post("/admin/test-notification", json={"channel": "email"}).status_code
        == 401
    )
    headers = {"X-API-Key": "TEST-ONLY-ADMIN-KEY"}
    assert (
        client.post(
            "/admin/test-notification", json={"channel": "invalid"}, headers=headers
        ).status_code
        == 400
    )
    result = client.post(
        "/admin/test-notification", json={"channel": "both"}, headers=headers
    )
    assert result.status_code == 200
    assert result.json["channels"]["email"]["success"] is True
