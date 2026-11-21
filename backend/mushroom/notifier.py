"""Bounded, send-only Gmail SMTP and Twilio notification delivery."""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from queue import Full, Queue
from threading import Lock, Thread
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .db import Database
from .i18n import MESSAGES

LOGGER = logging.getLogger(__name__)
EMAIL_RE = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
E164_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
MESSAGES_FOR_LOG = "email: disabled (not configured)"


class Notifier:
    """Queue alert delivery without blocking sensor requests or leaking contacts."""

    def __init__(
        self,
        settings: Any,
        database: Database,
        smtp_factory: Callable[..., Any] | None = None,
        twilio_factory: Callable[[], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        workers: int = 2,
        queue_capacity: int = 100,
        start_workers: bool = True,
    ) -> None:
        self.settings = settings
        self.database = database
        self.smtp_factory = smtp_factory
        self.twilio_factory = twilio_factory
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sleeper = sleeper
        self.email_recipients = tuple(
            item for item in settings.alert_emails if EMAIL_RE.fullmatch(item)
        )
        invalid_email_count = len(settings.alert_emails) - len(self.email_recipients)
        if invalid_email_count:
            LOGGER.warning(
                "Skipped %s invalid e-mail recipient setting(s)", invalid_email_count
            )
        self.sms_recipients = tuple(
            item for item in settings.alert_phones if E164_RE.fullmatch(item)
        )
        invalid_phone_count = len(settings.alert_phones) - len(self.sms_recipients)
        if invalid_phone_count:
            LOGGER.warning(
                "Skipped %s invalid SMS recipient setting(s)", invalid_phone_count
            )
        self.email_enabled = bool(
            settings.smtp_user and settings.smtp_password and self.email_recipients
        )
        self.sms_enabled = bool(
            settings.twilio_account_sid
            and settings.twilio_auth_token
            and E164_RE.fullmatch(settings.twilio_from)
            and self.sms_recipients
        )
        self._queue: Queue[Any] = Queue(maxsize=max(1, queue_capacity))
        self._lock = Lock()
        self._email_lock = Lock()
        self._threads: list[Thread] = []
        self._closed = False
        self._sms_client: Any = None
        self._daily_cap_warnings: set[str] = set()
        self._stats: dict[str, Any] = {
            "email_last_ok_ts": None,
            "email_last_error_class": None,
            "sms_last_ok_ts": None,
            "sms_last_error_class": None,
            "delivery_failures": {"email": 0, "sms": 0},
            "queued_digest_count": 0,
            "dropped_notifications": 0,
        }
        self._templates = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
        )
        if not self.email_enabled:
            LOGGER.info(MESSAGES_FOR_LOG)
        if not self.sms_enabled:
            LOGGER.info("sms: disabled (not configured)")
        if start_workers and (self.email_enabled or self.sms_enabled):
            for index in range(max(1, min(workers, 4))):
                thread = Thread(
                    target=self._worker,
                    name=f"mushroom-notifier-{index + 1}",
                    daemon=True,
                )
                thread.start()
                self._threads.append(thread)

    def health(self) -> dict[str, Any]:
        """Return delivery readiness and masked operational counters."""
        with self._lock:
            stats = dict(self._stats)
            stats["delivery_failures"] = dict(self._stats["delivery_failures"])
        return {
            **stats,
            "email_enabled": self.email_enabled,
            "sms_enabled": self.sms_enabled,
            "queue_size": self._queue.qsize(),
        }

    def enqueue(
        self, alert: dict[str, Any], channels: tuple[str, ...] | None = None
    ) -> bool:
        """Put a notification on a bounded queue and return immediately."""
        selected = channels or tuple(
            name
            for name, enabled in (
                ("email", self.email_enabled),
                ("sms", self.sms_enabled),
            )
            if enabled
        )
        selected = tuple(name for name in selected if name in {"email", "sms"})
        if self._closed or not selected:
            return False
        try:
            self._queue.put_nowait({"alert": dict(alert), "channels": selected})
        except Full:
            with self._lock:
                self._stats["dropped_notifications"] += 1
            LOGGER.error("Alert notification queue is full; delivery was not queued")
            return False
        return True

    def verify_smtp(self) -> str:
        """Check SMTP connectivity and authentication without sending a message."""
        if not (self.settings.smtp_user and self.settings.smtp_password):
            state = "email: disabled (not configured)"
            LOGGER.info(state)
            return state
        connection = None
        try:
            connection = self._new_smtp()
            connection.login(
                self.settings.smtp_user, self.settings.smtp_password.replace(" ", "")
            )
            state = "email: ready"
        except smtplib.SMTPAuthenticationError:
            state = "email: authentication failed (check the app password / 2-Step Verification)"
        except Exception:  # noqa: BLE001 - host errors may contain sensitive server details.
            state = "email: cannot reach SMTP server"
        finally:
            if connection is not None:
                self._close_smtp(connection)
        LOGGER.info(state)
        return state

    def send_test(self, channels: tuple[str, ...]) -> dict[str, Any]:
        """Queue a fixed test notice and wait for worker results for the admin endpoint."""
        result: dict[str, Any] = {}
        alert = {
            "type": "system-test",
            "message": "This is a test message from the mushroom monitor.",
            "location": "Farm monitor",
            "level": "low",
            "status": "info",
            "timestamp": self._now_text(),
        }
        for channel in channels:
            enabled = self.email_enabled if channel == "email" else self.sms_enabled
            if not enabled:
                result[channel] = {
                    "success": False,
                    "message": "This alert method is not set up yet.",
                }
                continue
            success = self._deliver_with_retry(channel, alert)
            result[channel] = {
                "success": success,
                "message": "Test sent."
                if success
                else "The test could not be sent. Check the alert settings.",
            }
        return result

    def flush_digest(self) -> bool:
        """Send queued over-cap alerts once a new local day has available capacity."""
        if not self.email_enabled:
            return False
        now = self._now()
        day = self._local_day(now)
        digest_path = f"meta/notification_digests/{day}"
        if self.database.get(digest_path):
            return False
        pending = self.database.get("meta/notification_queue") or {}
        if not isinstance(pending, dict) or not pending:
            return False
        with self._email_lock:
            count_path = f"meta/email_daily_count/{day}"
            count = int(self.database.get(count_path) or 0)
            if count >= self.settings.email_daily_cap:
                return False
            self.database.set(
                digest_path, {"status": "claimed", "created_at": now.isoformat()}
            )
            self.database.set(count_path, count + 1)
        language = self._language()
        summary_lines = [
            f"{item.get('location', 'Farm')}: {item.get('message', 'Alert')}"
            for item in pending.values()
            if isinstance(item, dict)
        ]
        digest_alert = {
            "type": "daily-digest",
            "message": f"{len(summary_lines)} alerts were held after the daily e-mail limit was reached.\n"
            + "\n".join(summary_lines[:100]),
            "location": self.settings.farm_name,
            "level": "low",
            "status": "info",
            "timestamp": self._now_text(),
        }
        sent = self._smtp_send(
            digest_alert,
            subject=MESSAGES[language]["digest_subject"],
            cap_reserved=True,
        )
        if sent:
            self.database.set(
                digest_path, {"status": "sent", "created_at": now.isoformat()}
            )
            for key in pending:
                self.database.delete(f"meta/notification_queue/{key}")
            self._record_success("email")
        else:
            with self._email_lock:
                current_count = int(self.database.get(count_path) or 0)
                self.database.set(count_path, max(0, current_count - 1))
            self.database.set(
                digest_path, {"status": "failed", "created_at": now.isoformat()}
            )
            self._record_failure("email", RuntimeError("SMTP delivery failed"))
        return sent

    def close(self, timeout: float = 5.0) -> None:
        """Stop notifier workers cleanly; queued messages finish within the timeout."""
        self._closed = True
        for _thread in self._threads:
            try:
                self._queue.put(None, timeout=max(0.1, timeout))
            except Full:
                LOGGER.warning("Notifier shutdown timed out while the queue was full")
                break
        for thread in self._threads:
            thread.join(timeout=max(0.0, timeout))
        self._threads.clear()

    def drain(self, timeout: float = 10.0) -> bool:
        """Wait up to the supplied time for queued items to finish (mainly for tests)."""
        deadline = time.monotonic() + max(0.0, timeout)
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        return self._queue.unfinished_tasks == 0

    def _worker(self) -> None:
        """Deliver queue entries on a small, fixed number of daemon workers."""
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                alert = item["alert"]
                for channel in item["channels"]:
                    if channel == "email":
                        try:
                            self.flush_digest()
                        except Exception as exc:  # noqa: BLE001 - an unavailable digest store must not kill workers.
                            self._record_failure("email", exc)
                    self._deliver_with_retry(channel, alert)
            finally:
                self._queue.task_done()

    def _deliver_with_retry(self, channel: str, alert: dict[str, Any]) -> bool:
        """Retry one channel three times with exponential backoff off-request."""
        for attempt in range(4):
            try:
                success = (
                    self._smtp_send(alert)
                    if channel == "email"
                    else self._sms_send(alert)
                )
                if success is None:
                    return True
                if success:
                    self._record_success(channel)
                    return True
                raise RuntimeError("Delivery is disabled")
            except Exception as exc:  # noqa: BLE001 - do not log provider details or contacts.
                self._record_failure(channel, exc)
                if attempt < 3:
                    self.sleeper(float(2**attempt))
        LOGGER.error(
            "%s alert delivery failed after retries (%s)",
            channel,
            self._error_class(channel),
        )
        return False

    def _smtp_send(
        self,
        alert: dict[str, Any],
        subject: str | None = None,
        cap_reserved: bool = False,
    ) -> bool | None:
        """Send one multipart message using Gmail SMTP only; no mailbox access."""
        if not self.email_enabled:
            return False
        now = self._now()
        day = self._local_day(now)
        count_path = f"meta/email_daily_count/{day}"
        if cap_reserved:
            return self._send_email_message(alert, subject)

        # Serialize the quota check and send so workers cannot exceed the daily cap.
        # Failed SMTP attempts do not consume a slot; retries remain possible.
        with self._email_lock:
            count = int(self.database.get(count_path) or 0)
            if count >= self.settings.email_daily_cap:
                self.database.push(
                    "meta/notification_queue",
                    {**alert, "queued_at": now.isoformat()},
                )
                with self._lock:
                    self._stats["queued_digest_count"] += 1
                if day not in self._daily_cap_warnings:
                    self._daily_cap_warnings.add(day)
                    LOGGER.warning(
                        "Daily e-mail limit reached; remaining alerts are queued for a digest"
                    )
                return None
            sent = self._send_email_message(alert, subject)
            if sent:
                self.database.set(count_path, count + 1)
            return sent

    def _send_email_message(self, alert: dict[str, Any], subject: str | None) -> bool:
        """Render and deliver one message after the daily cap has been checked."""

        local_time = self._local_time(alert.get("timestamp"))
        context = self._template_context(alert, local_time)
        message = EmailMessage()
        message["Subject"] = subject or MESSAGES[self._language()]["subject"].format(
            level=context["level_label"]
        )
        message["From"] = formataddr(
            (self.settings.email_from_name, self.settings.smtp_user)
        )
        message["To"] = "undisclosed-recipients:;"
        message["Bcc"] = ", ".join(self.email_recipients)
        if self.settings.email_reply_to:
            message["Reply-To"] = self.settings.email_reply_to
        message.set_content(self._templates.get_template("alert.txt").render(**context))
        message.add_alternative(
            self._templates.get_template("alert.html").render(**context), subtype="html"
        )
        connection = None
        try:
            connection = self._new_smtp()
            connection.login(
                self.settings.smtp_user, self.settings.smtp_password.replace(" ", "")
            )
            connection.send_message(message, to_addrs=list(self.email_recipients))
            LOGGER.info(
                "E-mail alert sent to %s recipient(s)", len(self.email_recipients)
            )
            return True
        finally:
            if connection is not None:
                self._close_smtp(connection)

    def _new_smtp(self) -> Any:
        """Create a configured SSL or STARTTLS connection with a finite timeout."""
        if self.smtp_factory:
            if self.settings.smtp_security == "ssl":
                return self.smtp_factory(
                    self.settings.smtp_host,
                    self.settings.smtp_port,
                    timeout=10,
                    context=ssl.create_default_context(),
                )
            return self.smtp_factory(
                self.settings.smtp_host, self.settings.smtp_port, timeout=10
            )
        if self.settings.smtp_security == "ssl":
            return smtplib.SMTP_SSL(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=10,
                context=ssl.create_default_context(),
            )
        connection = smtplib.SMTP(
            self.settings.smtp_host, self.settings.smtp_port, timeout=10
        )
        connection.ehlo()
        connection.starttls(context=ssl.create_default_context())
        connection.ehlo()
        return connection

    @staticmethod
    def _close_smtp(connection: Any) -> None:
        """Close an SMTP socket without logging a provider-supplied message."""
        try:
            connection.quit()
        except Exception as exc:  # noqa: BLE001 - closing an already-failed socket is harmless.
            LOGGER.debug("SMTP quit failed (%s)", type(exc).__name__)
            try:
                connection.close()
            except Exception as close_exc:  # noqa: BLE001 - never let cleanup affect alert handling.
                LOGGER.debug("SMTP close failed (%s)", type(close_exc).__name__)

    def _sms_send(self, alert: dict[str, Any]) -> bool:
        """Send a short SMS to configured E.164 recipients through Twilio."""
        if not self.sms_enabled:
            return False
        client = self._get_twilio_client()
        body = self._sms_body(alert)
        for recipient in self.sms_recipients:
            client.messages.create(
                body=body, from_=self.settings.twilio_from, to=recipient
            )
        LOGGER.info("SMS alert sent to %s recipient(s)", len(self.sms_recipients))
        return True

    def _get_twilio_client(self) -> Any:
        """Create the Twilio client lazily so offline mode has no provider side effects."""
        if self._sms_client is None:
            if self.twilio_factory:
                self._sms_client = self.twilio_factory()
            else:
                from twilio.rest import Client

                self._sms_client = Client(
                    self.settings.twilio_account_sid, self.settings.twilio_auth_token
                )
        return self._sms_client

    def _sms_body(self, alert: dict[str, Any]) -> str:
        """Build an ASCII-friendly short message and cap it at one SMS segment."""
        import unicodedata

        language = self._language()
        values = {
            "farm": self.settings.farm_name,
            "level": str(alert.get("level", "INFO")).upper(),
            "kind": str(alert.get("type", "Alert")),
            "location": str(alert.get("location", "Farm")),
            "message": str(alert.get("message", "Check the monitoring dashboard.")),
            "url": self.settings.dashboard_url,
        }
        body = MESSAGES[language]["sms"].format(**values)
        body = (
            unicodedata.normalize("NFKD", body)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        return body if len(body) <= 160 else f"{body[:157]}..."

    def _template_context(
        self, alert: dict[str, Any], local_time: str
    ) -> dict[str, str]:
        """Prepare escaped template fields and readable guidance for staff."""
        language = self._language()
        level = str(alert.get("level", "low")).lower()
        level_label = {"high": "HIGH", "med": "MEDIUM", "low": "INFO"}.get(
            level, "INFO"
        )
        if alert.get("type") == "sensor-offline":
            action = MESSAGES[language]["offline_action"]
        else:
            action = MESSAGES[language]["action"]
        value = alert.get("value")
        threshold = alert.get("threshold")
        reading = (
            f"{value} (target {threshold})"
            if value is not None and threshold is not None
            else "See the dashboard for the latest reading."
        )
        return {
            "language": language,
            "farm_name": self.settings.farm_name,
            "level_label": level_label,
            "message": str(
                alert.get("message", "A monitor alert needs your attention.")
            ),
            "location": str(alert.get("location", "Farm")),
            "reading": reading,
            "local_time": local_time,
            "action": action,
            "dashboard_url": self.settings.dashboard_url,
        }

    def _local_time(self, value: Any) -> str:
        """Format an alert time in the configured farm time zone."""
        try:
            text = str(value)
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(self._timezone()).strftime("%Y-%m-%d %H:%M %Z")
        except (TypeError, ValueError):
            return (
                self._now().astimezone(self._timezone()).strftime("%Y-%m-%d %H:%M %Z")
            )

    def _local_day(self, now: datetime) -> str:
        """Return the current date in the configured farm time zone."""
        return now.astimezone(self._timezone()).date().isoformat()

    def _timezone(self) -> Any:
        """Resolve the configured timezone with UTC as a safe fallback."""
        try:
            return ZoneInfo(self.settings.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return UTC

    def _language(self) -> str:
        """Use a supported template language, falling back safely to English."""
        return (
            self.settings.alert_language
            if self.settings.alert_language in MESSAGES
            else "en"
        )

    def _now(self) -> datetime:
        """Read the injected time source and normalize to UTC."""
        value = self.clock()
        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )

    def _now_text(self) -> str:
        """Return an explicit UTC timestamp for database entries."""
        return self._now().isoformat(timespec="seconds")

    def _record_success(self, channel: str) -> None:
        """Update a channel's last-success diagnostic timestamp."""
        with self._lock:
            self._stats[f"{channel}_last_ok_ts"] = self._now_text()
            self._stats[f"{channel}_last_error_class"] = None

    def _record_failure(self, channel: str, error: Exception) -> None:
        """Count a channel failure without retaining provider text or credentials."""
        with self._lock:
            self._stats["delivery_failures"][channel] += 1
            self._stats[f"{channel}_last_error_class"] = type(error).__name__

    def _error_class(self, channel: str) -> str:
        """Return only an exception class name for safe status/log display."""
        with self._lock:
            return str(self._stats[f"{channel}_last_error_class"] or "UnknownError")


def mask_email(address: str) -> str:
    """Mask an e-mail address for diagnostics while preserving its domain."""
    local, separator, domain = address.partition("@")
    if not separator:
        return "***"
    return f"{local[:2]}***@{domain}"


def mask_phone(number: str) -> str:
    """Mask a phone number while preserving its country prefix and last digits."""
    if len(number) < 7:
        return "***"
    return f"{number[:4]}***{number[-3:]}"
