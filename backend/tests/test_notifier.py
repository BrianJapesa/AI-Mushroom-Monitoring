"""Notifier tests use in-memory adapters and fake SMTP/Twilio clients only."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from backend.app import create_app
from backend.database import MemoryDemoStore
from backend.mushroom.config import Settings
from backend.mushroom.db import MemoryDB
from backend.mushroom.notifier import Notifier, mask_email, mask_phone


class FakeClock:
    """Mutable UTC clock for date cap and digest checks."""

    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, 9, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


class MailSink:
    """Collect test messages without opening a socket."""

    def __init__(self) -> None:
        self.messages: list[tuple[Any, list[str]]] = []


class FakeSMTP:
    """SMTP-shaped fake supporting both self-check and delivery."""

    def __init__(
        self,
        sink: MailSink,
        fail_send: bool = False,
        fail_login: bool = False,
    ) -> None:
        self.sink = sink
        self.fail_send = fail_send
        self.fail_login = fail_login

    def login(self, _user: str, _password: str) -> None:
        if self.fail_login:
            import smtplib

            raise smtplib.SMTPAuthenticationError(
                535, b"TEST-ONLY-ERROR recipient@example.test TEST-ONLY-PASSWORD"
            )

    def send_message(self, message: Any, to_addrs: list[str]) -> None:
        if self.fail_send:
            raise OSError("TEST-ONLY-ERROR recipient@example.test TEST-ONLY-PASSWORD")
        self.sink.messages.append((message, to_addrs))

    def quit(self) -> None:
        return None

    def close(self) -> None:
        return None


class FakeSMSMessages:
    """Twilio messages facade recording only test-target values."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def create(self, **values: str) -> None:
        self.sent.append(values)


class FakeTwilio:
    """Minimal client shape expected by the notifier."""

    def __init__(self) -> None:
        self.messages = FakeSMSMessages()


def build_test_settings(**overrides: Any) -> Settings:
    """Build test-only credentials and recipients; no real account data is used."""
    root = Path(__file__).resolve().parents[2]
    baseline = Settings.from_env(root / "backend" / ".env", root)
    values: dict[str, Any] = {
        "db_backend": "memory",
        "firebase_url": "",
        "api_key": "TEST-ONLY-API-KEY",
        "smtp_user": "sender@example.test",
        "smtp_password": "TEST-ONLY-PASSWORD",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "alert_emails": ("first@example.test", "second@example.test"),
        "email_daily_cap": 10,
        "twilio_account_sid": "TEST-ONLY-SID",
        "twilio_auth_token": "TEST-ONLY-TOKEN",
        "twilio_from": "+254700000001",
        "alert_phones": ("+254700000002",),
    }
    values.update(overrides)
    return replace(baseline, **values)


def sample_alert() -> dict[str, str]:
    """Return a labelled test alert, never a farm observation."""
    return {
        "type": "TEST-ONLY-humidity-low",
        "message": "TEST-ONLY: humidity is below the example limit.",
        "location": "TEST-ONLY-Room 1",
        "level": "med",
        "status": "open",
        "timestamp": "2026-01-01T09:00:00+00:00",
        "value": "76",
        "threshold": "80",
    }


def test_multipart_bcc_email_and_cap_digest_idempotency(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = MailSink()
    clock = FakeClock()
    settings = build_test_settings(email_daily_cap=1)
    notifier = Notifier(
        settings,
        MemoryDB(),
        smtp_factory=lambda *_args, **_kwargs: FakeSMTP(sink),
        clock=clock,
        sleeper=lambda _seconds: None,
        start_workers=False,
    )
    caplog.set_level("INFO")
    unsafe_alert = {**sample_alert(), "message": "TEST-ONLY <script>alert(1)</script>"}
    assert notifier._deliver_with_retry("email", unsafe_alert) is True
    message, envelope = sink.messages[0]
    assert message.is_multipart()
    assert message.get_content_type() == "multipart/alternative"
    assert "undisclosed-recipients" in message["To"]
    assert "first@example.test" in message["Bcc"]
    assert set(envelope) == {"first@example.test", "second@example.test"}
    assert "<script>" not in message.get_body(preferencelist=("html",)).get_content()
    assert "first@example.test" not in caplog.text

    assert notifier._deliver_with_retry("email", sample_alert()) is True
    assert len(sink.messages) == 1
    assert len(notifier.database.get("meta/notification_queue")) == 1
    clock.value += timedelta(days=1)
    assert notifier.flush_digest() is True
    assert notifier.flush_digest() is False
    assert len(sink.messages) == 2
    assert notifier.database.get("meta/notification_queue") == {}


def test_smtp_self_check_has_safe_states_and_retry_errors_are_masked(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = MailSink()
    clock = FakeClock()
    notifier = Notifier(
        build_test_settings(email_daily_cap=1),
        MemoryDB(),
        smtp_factory=lambda *_args, **_kwargs: FakeSMTP(sink, fail_login=True),
        clock=clock,
        sleeper=lambda _seconds: None,
        start_workers=False,
    )
    caplog.set_level("INFO")
    assert (
        notifier.verify_smtp()
        == "email: authentication failed (check the app password / 2-Step Verification)"
    )
    assert "TEST-ONLY-PASSWORD" not in caplog.text
    assert "recipient@example.test" not in caplog.text
    notifier.smtp_factory = lambda *_args, **_kwargs: FakeSMTP(sink, fail_send=True)
    assert notifier._deliver_with_retry("email", sample_alert()) is False
    health = notifier.health()
    assert health["delivery_failures"]["email"] == 4
    assert health["email_last_error_class"] == "OSError"
    assert notifier.database.get("meta/email_daily_count/2026-01-01") == {}
    assert notifier.database.get("meta/notification_queue") == {}
    assert "TEST-ONLY-PASSWORD" not in caplog.text


def test_disabled_notifier_sms_validation_and_short_ascii_message() -> None:
    disabled = Notifier(
        build_test_settings(
            smtp_user="",
            smtp_password="",
            alert_emails=(),
            twilio_account_sid="",
            twilio_auth_token="",
            twilio_from="",
            alert_phones=(),
        ),
        MemoryDB(),
        start_workers=False,
    )
    assert disabled.verify_smtp() == "email: disabled (not configured)"
    assert disabled.health()["email_enabled"] is False
    assert disabled.health()["sms_enabled"] is False

    client = FakeTwilio()
    sms = Notifier(
        build_test_settings(
            smtp_user="",
            smtp_password="",
            alert_emails=(),
            alert_phones=("bad-number",),
        ),
        MemoryDB(),
        twilio_factory=lambda: client,
        sleeper=lambda _seconds: None,
        start_workers=False,
    )
    assert sms.health()["sms_enabled"] is False
    assert len(sms._sms_body(sample_alert())) <= 160
    assert sms._sms_body(sample_alert()).isascii()
    assert mask_email("someone@example.test") == "so***@example.test"
    assert mask_phone("+254700000002") == "+254***002"


def test_sms_delivery_uses_e164_and_no_long_messages() -> None:
    client = FakeTwilio()
    notifier = Notifier(
        build_test_settings(smtp_user="", smtp_password="", alert_emails=()),
        MemoryDB(),
        twilio_factory=lambda: client,
        sleeper=lambda _seconds: None,
        start_workers=False,
    )
    assert notifier._deliver_with_retry("sms", sample_alert()) is True
    assert len(client.messages.sent) == 1
    assert client.messages.sent[0]["to"] == "+254700000002"
    assert len(client.messages.sent[0]["body"]) <= 160


def test_bounded_notification_queue_and_no_mailbox_imports() -> None:
    notifier = Notifier(
        build_test_settings(), MemoryDB(), queue_capacity=1, start_workers=False
    )
    assert notifier.enqueue(sample_alert()) is True
    assert notifier.enqueue(sample_alert()) is False
    assert notifier.health()["dropped_notifications"] == 1

    package = Path(__file__).resolve().parents[1] / "mushroom"
    imports: list[str] = []
    for path in package.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "imaplib" not in text
        assert "poplib" not in text
        imports.append(text)
    assert imports


def test_sensor_response_does_not_wait_for_failed_notification(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = MailSink()
    settings = build_test_settings(
        twilio_account_sid="",
        twilio_auth_token="",
        twilio_from="",
        alert_phones=(),
    )
    database = MemoryDB()
    notifier = Notifier(
        settings,
        database,
        smtp_factory=lambda *_args, **_kwargs: FakeSMTP(sink, fail_send=True),
        sleeper=lambda _seconds: None,
        start_workers=True,
    )
    app = create_app(
        store=MemoryDemoStore(),
        database=database,
        settings=settings,
        notifier=notifier,
    )
    client = app.test_client()
    caplog.set_level("INFO")
    response = client.post(
        "/sensor",
        json={"temperature": 24, "humidity": 76, "synthetic": True},
        headers={"X-API-Key": "TEST-ONLY-API-KEY"},
    )
    assert response.status_code == 200
    assert response.json["status"] == "received"
    assert notifier.drain(timeout=3)
    health = client.get("/health").json
    assert health["notification_failures"]["email"] == 4
    assert health["email_last_error_class"] == "OSError"
    assert "TEST-ONLY-PASSWORD" not in caplog.text
    assert "recipient@example.test" not in caplog.text
    notifier.close()
