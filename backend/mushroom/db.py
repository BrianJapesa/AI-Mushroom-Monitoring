"""Small Firebase and in-memory database adapters."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any, Protocol


class Database(Protocol):
    """Database operations required by API and alert modules."""

    name: str

    def get(self, path: str) -> Any: ...
    def set(self, path: str, value: Any) -> None: ...
    def push(self, path: str, value: dict[str, Any]) -> str: ...
    def delete(self, path: str) -> None: ...
    def query(self, path: str, limit: int = 100) -> list[dict[str, Any]]: ...


class DatabaseUnavailable(RuntimeError):
    """Provider access failed; safe to report as a temporary service outage."""


class MemoryDB:
    """Thread-safe in-memory database for offline development and tests."""

    name = "memory"

    def __init__(self) -> None:
        self._data: dict[str, Any] = {
            "sensors": {},
            "records": {},
            "bags": {},
            "bag_history": {},
            "alerts": {},
            "meta": {},
        }
        self._lock = RLock()
        self._counter = 0

    def get(self, path: str) -> Any:
        """Return a deep copy so callers cannot mutate shared state outside the lock."""
        with self._lock:
            return deepcopy(_read(self._data, path))

    def set(self, path: str, value: Any) -> None:
        """Set a database value at a validated slash-separated path."""
        with self._lock:
            _write(self._data, path, deepcopy(value))

    def push(self, path: str, value: dict[str, Any]) -> str:
        """Append a record using deterministic local keys for repeatable tests."""
        with self._lock:
            self._counter += 1
            key = f"local-{self._counter:08d}"
            _write(self._data, f"{path}/{key}", deepcopy(value))
            return key

    def delete(self, path: str) -> None:
        """Remove one database path if it exists."""
        with self._lock:
            parts = _parts(path)
            parent = (
                _read(self._data, "/".join(parts[:-1]))
                if len(parts) > 1
                else self._data
            )
            if isinstance(parent, dict):
                parent.pop(parts[-1], None)

    def query(self, path: str, limit: int = 100) -> list[dict[str, Any]]:
        """Return newest records first, matching Realtime Database UI semantics."""
        values = _read(self._data, path)
        if isinstance(values, dict):
            records = [item for item in values.values() if isinstance(item, dict)]
        elif isinstance(values, list):
            records = [item for item in values if isinstance(item, dict)]
        else:
            records = []
        records.reverse()
        records.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
        return deepcopy(records[: max(1, min(limit, 500))])


class FirebaseDB:
    """Firebase Realtime Database adapter using a local service-account key."""

    name = "firebase"

    def __init__(self, database_url: str, credential_file: str) -> None:
        """Connect through the Admin SDK without exposing credential data."""
        from pathlib import Path

        import firebase_admin
        from firebase_admin import credentials, db

        key_path = Path(credential_file)
        if not key_path.is_file():
            raise FileNotFoundError(
                "Firebase service-account file was not found in backend/secrets."
            )
        try:
            app = firebase_admin.get_app("mushroom_api")
        except ValueError:
            app = firebase_admin.initialize_app(
                credentials.Certificate(str(key_path)),
                {"databaseURL": database_url.rstrip("/")},
                name="mushroom_api",
            )
        self._root = db.reference("/", app=app)

    def get(self, path: str) -> Any:
        """Read one validated path from Firebase."""
        return self._call(lambda: self._reference(path).get())

    def set(self, path: str, value: Any) -> None:
        """Write one validated path to Firebase."""
        self._call(lambda: self._reference(path).set(value))

    def push(self, path: str, value: dict[str, Any]) -> str:
        """Append a record and return Firebase's generated child key."""
        return str(self._call(lambda: self._reference(path).push(value).key))

    def delete(self, path: str) -> None:
        """Remove one validated path from Firebase."""
        self._call(lambda: self._reference(path).delete())

    def query(self, path: str, limit: int = 100) -> list[dict[str, Any]]:
        """Return newest records first from Firebase query results."""
        value = self._call(lambda: self._reference(path).get()) or {}
        records = (
            list(value.values())
            if isinstance(value, dict)
            else value
            if isinstance(value, list)
            else []
        )
        result = [item for item in records if isinstance(item, dict)]
        result.reverse()
        result.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
        return result[: max(1, min(limit, 500))]

    def _reference(self, path: str) -> Any:
        """Resolve and validate a relative database path."""
        parts = _parts(path)
        ref = self._root
        for part in parts:
            ref = ref.child(part)
        return ref

    @staticmethod
    def _call(operation: Any) -> Any:
        """Convert provider exceptions to a generic error without logging secrets."""
        try:
            return operation()
        except Exception as exc:
            raise DatabaseUnavailable(
                "Database service is temporarily unavailable."
            ) from exc


def _parts(path: str) -> list[str]:
    """Reject Firebase-reserved key characters before resolving a path."""
    parts = [part for part in path.strip("/").split("/") if part]
    if not parts or any(any(char in part for char in ".$#[]") for part in parts):
        raise ValueError("Database path contains an invalid key.")
    if any(len(part) > 128 for part in parts):
        raise ValueError("Database path key is too long.")
    return parts


def _read(root: dict[str, Any], path: str) -> Any:
    """Read a nested mapping, returning an empty mapping for missing paths."""
    node: Any = root
    for part in _parts(path):
        node = node.get(part, {}) if isinstance(node, dict) else {}
    return node


def _write(root: dict[str, Any], path: str, value: Any) -> None:
    """Create mapping parents and set a leaf value."""
    parts = _parts(path)
    node = root
    for part in parts[:-1]:
        child = node.setdefault(part, {})
        if not isinstance(child, dict):
            raise TypeError("Database path conflicts with an existing value.")
        node = child
    node[parts[-1]] = value
