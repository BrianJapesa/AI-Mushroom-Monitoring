"""Shared adapter contract checks run against memory and a fake Firebase SDK."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from backend.mushroom.db import DatabaseUnavailable, FirebaseDB, MemoryDB


class FakeReference:
    """Small Firebase-shaped node for tests; it never accesses a real project."""

    def __init__(self, state: dict[str, Any], path: tuple[str, ...] = ()) -> None:
        self.state = state
        self.path = path
        self.key: str | None = None

    def child(self, part: str) -> FakeReference:
        return FakeReference(self.state, (*self.path, part))

    def _node(self) -> Any:
        node: Any = self.state
        for part in self.path:
            node = node.get(part, {}) if isinstance(node, dict) else {}
        return node

    def get(self) -> Any:
        return deepcopy(self._node())

    def set(self, value: Any) -> None:
        self._parent()[self.path[-1]] = deepcopy(value)

    def update(self, values: dict[str, Any]) -> None:
        for path, value in values.items():
            parts = tuple(path.split("/"))
            node: Any = self.state
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            if value is None:
                node.pop(parts[-1], None)
            else:
                node[parts[-1]] = deepcopy(value)

    def delete(self) -> None:
        self._parent().pop(self.path[-1], None)

    def push(self, value: Any = None) -> FakeReference:
        self.state["__test_counter"] = self.state.get("__test_counter", 0) + 1
        child = self.child(f"-fake-{self.state['__test_counter']:08d}")
        child.key = child.path[-1]
        if value is not None:
            child.set(value)
        return child

    def _parent(self) -> dict[str, Any]:
        node = self.state
        for part in self.path[:-1]:
            node = node.setdefault(part, {})
        return node


def assert_adapter_contract(database: Any) -> None:
    """Assert timestamp/key ordering, limit-to-last, atomic update, and delete."""
    database.set(
        "records/seed", {"timestamp": "2026-01-01T00:00:00+00:00", "value": "seed"}
    )
    older = database.push(
        "records", {"timestamp": "2026-01-02T00:00:00+00:00", "value": "older"}
    )
    latest = database.push(
        "records", {"timestamp": "2026-01-03T00:00:00+00:00", "value": "latest"}
    )
    assert older != latest
    assert database.query("records", 1)[0]["value"] == "latest"
    assert database.query("records", 0) == []
    same_time = "2026-01-04T00:00:00+00:00"
    database.push("records", {"timestamp": same_time, "value": "same-time-first"})
    database.push("records", {"timestamp": same_time, "value": "same-time-latest"})
    assert database.query("records", 1)[0]["value"] == "same-time-latest"
    database.update(
        {"sensors/latest": {"temperature": 24}, "records/atomic": {"value": "yes"}}
    )
    assert database.get("sensors/latest")["temperature"] == 24
    assert database.get("records/atomic")["value"] == "yes"
    database.update({"records/seed": None})
    assert database.get("records/seed") == {}


def test_memory_adapter_contract() -> None:
    assert_adapter_contract(MemoryDB())


def test_firebase_fake_adapter_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state: dict[str, Any] = {}
    root = FakeReference(state)
    fake_app = object()
    credentials = type(
        "Credentials", (), {"Certificate": staticmethod(lambda _path: object())}
    )
    db_module = type(
        "DatabaseModule",
        (),
        {"reference": staticmethod(lambda *_args, **_kwargs: root)},
    )
    admin = type(
        "FirebaseAdmin",
        (),
        {
            "credentials": credentials,
            "db": db_module,
            "get_app": staticmethod(
                lambda _name: (_ for _ in ()).throw(ValueError("missing"))
            ),
            "initialize_app": staticmethod(lambda *_args, **_kwargs: fake_app),
        },
    )
    monkeypatch.setitem(__import__("sys").modules, "firebase_admin", admin)
    monkeypatch.setitem(
        __import__("sys").modules, "firebase_admin.credentials", credentials
    )
    monkeypatch.setitem(__import__("sys").modules, "firebase_admin.db", db_module)
    key = tmp_path / "service-key-test.json"
    key.write_text("{}", encoding="utf-8")
    database = FirebaseDB("https://example.invalid", str(key))
    assert_adapter_contract(database)


def test_database_unavailable_wraps_provider_error() -> None:
    with pytest.raises(DatabaseUnavailable):
        FirebaseDB._call(lambda: (_ for _ in ()).throw(OSError("test provider error")))
