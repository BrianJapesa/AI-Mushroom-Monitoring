"""Synthetic demo fixtures for the offline prototype.

All values in this module are generated examples and do not describe the farm.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import sin
from typing import Any

SYNTHETIC_SCENARIOS = {
    "normal": (24.4, 86.0),
    "warm": (28.2, 85.0),
    "dry": (24.1, 74.0),
}


def build_synthetic_demo_state() -> dict[str, Any]:
    """Build synthetic room records, example alerts, and example bag checks."""
    now = datetime.now(UTC)
    records = []
    for hour in range(24):
        stamp = now - timedelta(hours=23 - hour)
        records.append({
            "temperature": round(24.0 + sin(hour / 3) * 1.2, 1),
            "humidity": round(85.0 + sin(hour / 2.7) * 3.0, 1),
            "room": "Room 1",
            "device_id": "SYNTHETIC-DEMO-SENSOR",
            "timestamp": stamp.isoformat(timespec="seconds"),
            "synthetic": True,
        })
    latest = {**records[-1], "temperature": 24.4, "humidity": 86.0, "timestamp": now.isoformat(timespec="seconds")}
    alerts = [{
        "id": "SYNTHETIC-DEMO-ALERT-001",
        "type": "Example only",
        "level": "low",
        "status": "demo",
        "location": "Room 1",
        "message": "This sample alert is for the demo. It is not a real farm warning.",
        "timestamp": (now - timedelta(minutes=18)).isoformat(timespec="seconds"),
        "synthetic": True,
    }]
    bags = [
        {"id": "DEMO-BAG-001", "status": "example", "room": "Room 1", "timestamp": (now - timedelta(hours=2)).isoformat(timespec="seconds"), "synthetic": True},
        {"id": "DEMO-BAG-002", "status": "example", "room": "Room 1", "timestamp": (now - timedelta(hours=5)).isoformat(timespec="seconds"), "synthetic": True},
        {"id": "DEMO-BAG-003", "status": "example", "room": "Room 1", "timestamp": (now - timedelta(hours=8)).isoformat(timespec="seconds"), "synthetic": True},
    ]
    return {"latest": latest, "records": records, "alerts": alerts, "bags": bags, "sequence": 0}
