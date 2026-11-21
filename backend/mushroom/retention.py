"""Opt-in record-retention cleanup with an explicit dry-run mode."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from .db import Database


class RetentionJob:
    """Find expired records and delete them only when retention is enabled."""

    def __init__(
        self,
        database: Database,
        retention_days: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = database
        self.retention_days = max(0, retention_days)
        self.clock = clock or (lambda: datetime.now(UTC))

    def run(self, dry_run: bool = True) -> dict[str, int | bool]:
        """Return candidate/deleted counts without exposing record contents."""
        if self.retention_days == 0:
            return {"enabled": False, "candidates": 0, "deleted": 0}
        now = self.clock()
        now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
        cutoff = now - timedelta(days=self.retention_days)
        records = self.database.get("records") or {}
        items = (
            records.items()
            if isinstance(records, dict)
            else enumerate(records)
            if isinstance(records, list)
            else ()
        )
        expired = [
            str(key)
            for key, value in items
            if isinstance(value, dict) and _timestamp(value.get("timestamp")) < cutoff
        ]
        if not dry_run:
            for key in expired:
                self.database.delete(f"records/{key}")
        return {
            "enabled": True,
            "candidates": len(expired),
            "deleted": 0 if dry_run else len(expired),
        }


def _timestamp(value: Any) -> datetime:
    """Parse stored UTC time, treating malformed data as oldest for cleanup."""
    try:
        text = str(value)
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
        return (
            parsed.replace(tzinfo=UTC)
            if parsed.tzinfo is None
            else parsed.astimezone(UTC)
        )
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, UTC)
