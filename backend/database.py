"""Demo database adapters: local memory and Firebase Realtime Database."""
from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock
from typing import Any, Protocol

try:
    from .synthetic_demo_data import build_synthetic_demo_state
except ImportError:  # Support direct execution from backend/app.py.
    from synthetic_demo_data import build_synthetic_demo_state

LOGGER = logging.getLogger(__name__)


class DemoStore(Protocol):
    """Storage contract used by the presentation dashboard."""

    backend_name: str

    def get_dashboard(self) -> dict[str, Any]:
        """Return the current demo dashboard data."""
        ...

    def add_reading(self, reading: dict[str, Any], alert: dict[str, Any] | None) -> None:
        """Save one clearly synthetic reading and optional example alert."""
        ...

    def reset(self) -> None:
        """Restore the initial synthetic demo examples."""
        ...


class MemoryDemoStore:
    """Keep synthetic presentation data in memory for offline demonstrations."""

    backend_name = "memory"

    def __init__(self) -> None:
        self._lock = Lock()
        self._data = build_synthetic_demo_state()

    def get_dashboard(self) -> dict[str, Any]:
        """Return a consistent snapshot of the in-memory example data."""
        with self._lock:
            return {**self._data, "records": list(self._data["records"]), "alerts": list(self._data["alerts"]), "bags": list(self._data["bags"])}

    def add_reading(self, reading: dict[str, Any], alert: dict[str, Any] | None) -> None:
        """Append a simulated reading and optional simulated alert."""
        with self._lock:
            self._data["sequence"] += 1
            self._data["latest"] = reading
            self._data["records"].append(reading)
            self._data["records"] = self._data["records"][-200:]
            if alert is not None:
                alert["id"] = f"SYNTHETIC-DEMO-ALERT-{self._data['sequence']:03d}"
                self._data["alerts"].insert(0, alert)
                self._data["alerts"] = self._data["alerts"][:50]

    def reset(self) -> None:
        """Replace current data with a fresh set of synthetic examples."""
        with self._lock:
            self._data = build_synthetic_demo_state()


class FirebaseDemoStore:
    """Read and write presentation-only data in Firebase's `/demo` node."""

    backend_name = "firebase"

    def __init__(self, database_url: str, credential_file: Path) -> None:
        """Connect using a client-owned service-account file, never a chat secret."""
        if not database_url.startswith("https://"):
            raise ValueError("FIREBASE_URL must start with https://.")
        if not credential_file.is_file():
            raise FileNotFoundError("Firebase service-account file is missing from backend/secrets.")

        import firebase_admin
        from firebase_admin import credentials, db

        try:
            firebase_app = firebase_admin.get_app("mushroom_presentation")
        except ValueError:
            credential = credentials.Certificate(str(credential_file))
            firebase_app = firebase_admin.initialize_app(
                credential,
                {"databaseURL": database_url},
                name="mushroom_presentation",
            )
        self._reference = db.reference("demo", app=firebase_app)
        self._lock = Lock()
        if not self._reference.get():
            self.reset()
        LOGGER.info("Firebase presentation demo is ready; data is stored under /demo")

    def get_dashboard(self) -> dict[str, Any]:
        """Read demo records and sort them by their UTC timestamp."""
        with self._lock:
            raw = self._reference.get() or {}
        records = self._values(raw.get("records"))
        alerts = self._values(raw.get("alerts"))
        bags = self._values(raw.get("bags"))
        records.sort(key=lambda item: item.get("timestamp", ""))
        alerts.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        bags.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        return {
            "latest": raw.get("latest") or {},
            "records": records[-200:],
            "alerts": alerts[:50],
            "bags": bags,
            "sequence": int(raw.get("sequence", 0)),
        }

    def add_reading(self, reading: dict[str, Any], alert: dict[str, Any] | None) -> None:
        """Persist a simulated sample in Firebase so the frontend can read it back."""
        with self._lock:
            self._reference.child("latest").set(reading)
            self._reference.child("records").push(reading)
            if alert is not None:
                alert_reference = self._reference.child("alerts").push()
                saved_alert = {**alert, "id": alert_reference.key}
                alert_reference.set(saved_alert)
            self._reference.child("sequence").set(int(self._reference.child("sequence").get() or 0) + 1)

    def reset(self) -> None:
        """Replace only the `/demo` presentation node with labeled examples."""
        with self._lock:
            self._reference.set(build_synthetic_demo_state())

    @staticmethod
    def _values(value: Any) -> list[dict[str, Any]]:
        """Convert Firebase's object/list representation to plain records."""
        if isinstance(value, list):
            candidates = value
        elif isinstance(value, dict):
            candidates = list(value.values())
        else:
            candidates = []
        return [item for item in candidates if isinstance(item, dict)]
