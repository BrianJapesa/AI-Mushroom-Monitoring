"""Structured, rotating logs with request IDs and contact/secret masking."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any

from flask import g, has_request_context

_CONFIG_LOCK = Lock()
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PHONE = re.compile(r"(?<!\w)\+\d[\d ()-]{6,}\d")
_SECRET = re.compile(
    r"(?i)\b(api[_ -]?key|password|token|secret)\b\s*[:=]\s*([^\s,;]+)"
)


def mask_personal_data(message: str) -> str:
    """Mask e-mail, E.164 phone, and inline secret-like values in one log string."""
    message = _EMAIL.sub(_mask_email_match, message)
    message = _PHONE.sub(_mask_phone_match, message)
    return _SECRET.sub(lambda match: f"{match.group(1)}=<redacted>", message)


def _mask_email_match(match: re.Match[str]) -> str:
    """Mask the local part while preserving enough domain context for support."""
    local, _at, domain = match.group(0).partition("@")
    return f"{local[:2]}***@{domain}"


def _mask_phone_match(match: re.Match[str]) -> str:
    """Mask most digits while keeping country prefix and last three digits."""
    digits = re.sub(r"\D", "", match.group(0))
    prefix = f"+{digits[:3]}" if digits else "+***"
    return f"{prefix}***{digits[-3:]}"


class PIIMaskingFilter(logging.Filter):
    """Redact personal data before any configured handler formats a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:  # noqa: BLE001 - a malformed log message must not break the app.
            rendered = "[unavailable log message]"
        record.msg = mask_personal_data(rendered)
        record.args = ()
        return True


class JsonLogFormatter(logging.Formatter):
    """Format compact JSON lines without stack traces or raw exception messages."""

    def format(self, record: logging.LogRecord) -> str:
        request_id = "-"
        if has_request_context():
            request_id = str(getattr(g, "request_id", "-"))
        event: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id,
            "message": mask_personal_data(record.getMessage()),
        }
        if record.exc_info and record.exc_info[0]:
            event["error_class"] = record.exc_info[0].__name__
        return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def configure_logging(log_directory: Path) -> None:
    """Install one rotating UTF-8 JSON log file handler per process."""
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = (log_directory / "monitoring.log").resolve()
    with _CONFIG_LOCK:
        root = logging.getLogger()
        if any(
            getattr(handler, "_mushroom_log_path", None) == log_path
            for handler in root.handlers
        ):
            return
        handler = RotatingFileHandler(
            log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        handler._mushroom_log_path = log_path  # type: ignore[attr-defined]
        handler.addFilter(PIIMaskingFilter())
        handler.setFormatter(JsonLogFormatter())
        root.addHandler(handler)
        if root.level == logging.NOTSET:
            root.setLevel(logging.INFO)
