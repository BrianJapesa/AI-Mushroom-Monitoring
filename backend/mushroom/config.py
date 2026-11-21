"""Validated application settings loaded from backend/.env."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Typed runtime configuration shared by the backend modules."""

    db_backend: str
    firebase_url: str
    firebase_credentials: Path
    api_key: str
    temp_min: float
    temp_max: float
    hum_min: float
    hum_max: float
    recovery_margin_temp: float
    recovery_margin_humidity: float
    alert_cooldown_seconds: int
    max_upload_bytes: int
    min_confidence: float
    timezone: str
    cors_origins: tuple[str, ...]
    escalation_minutes: int
    sensor_stale_minutes: int
    smtp_user: str
    smtp_password: str
    smtp_host: str
    smtp_port: int
    smtp_security: str
    email_from_name: str
    email_reply_to: str
    alert_emails: tuple[str, ...]
    email_daily_cap: int
    dashboard_url: str
    alert_language: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_from: str
    alert_phones: tuple[str, ...]
    farm_name: str
    retention_days_records: int

    @classmethod
    def from_env(cls, env_file: Path, root: Path) -> Settings:
        """Load and validate configuration so bad settings fail clearly at startup."""
        load_dotenv(env_file, override=False)
        configured_url = os.getenv("FIREBASE_URL", "").strip()
        backend = (
            os.getenv("DB_BACKEND", "firebase" if configured_url else "memory")
            .strip()
            .lower()
        )
        if backend not in {"memory", "firebase"}:
            raise ValueError("DB_BACKEND must be memory or firebase.")

        firebase_url = configured_url.rstrip("/")
        if backend == "firebase" and not firebase_url.startswith("https://"):
            raise ValueError(
                "Firebase mode needs a Realtime Database URL beginning with https://."
            )

        credential_setting = Path(
            os.getenv("FIREBASE_CREDENTIALS", "backend/secrets/serviceAccountKey.json")
        )
        credential_path = (
            credential_setting
            if credential_setting.is_absolute()
            else root / credential_setting
        )
        settings = cls(
            db_backend=backend,
            firebase_url=firebase_url,
            firebase_credentials=credential_path,
            api_key=os.getenv("API_KEY", "").strip(),
            temp_min=_number("TEMP_MIN", 22.0),
            temp_max=_number("TEMP_MAX", 26.0),
            hum_min=_number("HUM_MIN", 80.0),
            hum_max=_number("HUM_MAX", 90.0),
            recovery_margin_temp=_number("RECOVERY_MARGIN_TEMP", 1.0),
            recovery_margin_humidity=_number("RECOVERY_MARGIN_HUMIDITY", 2.0),
            alert_cooldown_seconds=_integer("ALERT_COOLDOWN", 600),
            max_upload_bytes=_integer("MAX_UPLOAD_MB", 8) * 1024 * 1024,
            min_confidence=_number("MIN_CONFIDENCE", 0.55),
            timezone=os.getenv("TIMEZONE", "Africa/Nairobi").strip(),
            cors_origins=tuple(
                item.strip()
                for item in os.getenv("CORS_ORIGINS", "").split(",")
                if item.strip()
            ),
            escalation_minutes=_integer("ESCALATE_AFTER_MIN", 30),
            sensor_stale_minutes=_integer("SENSOR_STALE_MIN", 10),
            smtp_user=os.getenv("SMTP_USER", "").strip(),
            smtp_password=os.getenv("SMTP_PASS", ""),
            smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com").strip(),
            smtp_port=_integer("SMTP_PORT", 465),
            smtp_security=os.getenv("SMTP_SECURITY", "ssl").strip().lower(),
            email_from_name=os.getenv(
                "EMAIL_FROM_NAME", "Japesa Farms Monitor"
            ).strip(),
            email_reply_to=os.getenv("EMAIL_REPLY_TO", "").strip(),
            alert_emails=_list_setting("ALERT_EMAILS", "ALERT_EMAIL"),
            email_daily_cap=_integer("EMAIL_DAILY_CAP", 100),
            dashboard_url=os.getenv("DASHBOARD_URL", "http://127.0.0.1:5000/").strip(),
            alert_language=os.getenv("ALERT_LANGUAGE", "en").strip().lower(),
            twilio_account_sid=os.getenv("TWILIO_SID", "").strip(),
            twilio_auth_token=os.getenv("TWILIO_TOKEN", ""),
            twilio_from=os.getenv("TWILIO_FROM", "").strip(),
            alert_phones=_list_setting("ALERT_PHONES", "ALERT_PHONE"),
            farm_name=os.getenv("FARM_NAME", "Japesa Farms").strip(),
            retention_days_records=_integer("RETENTION_DAYS_RECORDS", 0),
        )
        if (
            settings.temp_min >= settings.temp_max
            or settings.hum_min >= settings.hum_max
        ):
            raise ValueError(
                "Minimum temperature and humidity limits must be lower than their maximums."
            )
        if (
            settings.alert_cooldown_seconds < 0
            or settings.max_upload_bytes < 1024
            or settings.escalation_minutes < 1
            or settings.sensor_stale_minutes < 1
        ):
            raise ValueError("Cooldown and upload size settings must be positive.")
        if not 0.0 <= settings.min_confidence <= 1.0:
            raise ValueError("MIN_CONFIDENCE must be between 0 and 1.")
        if settings.smtp_security not in {"ssl", "starttls"}:
            raise ValueError("SMTP_SECURITY must be ssl or starttls.")
        if settings.smtp_port not in {465, 587} or settings.email_daily_cap < 1:
            raise ValueError(
                "SMTP_PORT must be 465 or 587 and EMAIL_DAILY_CAP must be positive."
            )
        if (settings.smtp_security == "ssl" and settings.smtp_port != 465) or (
            settings.smtp_security == "starttls" and settings.smtp_port != 587
        ):
            raise ValueError("Use SSL with port 465 or STARTTLS with port 587.")
        if settings.alert_language not in {"en", "sw"}:
            raise ValueError("ALERT_LANGUAGE must be en or sw.")
        if settings.retention_days_records < 0:
            raise ValueError("RETENTION_DAYS_RECORDS cannot be negative.")
        return settings


def _number(name: str, default: float) -> float:
    """Read a finite numeric environment setting."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite.")
    return result


def _integer(name: str, default: int) -> int:
    """Read an integer environment setting."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number.") from exc


def _list_setting(primary: str, legacy: str) -> tuple[str, ...]:
    """Read a comma-separated setting and fall back to a legacy single value."""
    value = os.getenv(primary, "").strip() or os.getenv(legacy, "").strip()
    return tuple(item.strip() for item in value.split(",") if item.strip())
