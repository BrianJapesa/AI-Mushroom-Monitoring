"""Checks for the synthetic Kenyan-context prototype API and stores."""
from typing import Any

import backend.app as app_module
from backend.app import create_app
from backend.database import FirebaseDemoStore, MemoryDemoStore


class FakeReference:
    """Small in-memory Firebase reference used only in unit tests."""

    def __init__(self, state: dict[str, Any], path: tuple[str, ...] = ()) -> None:
        self.state = state
        self.path = path

    def _node(self) -> Any:
        node: Any = self.state
        for part in self.path:
            node = node.get(part, {}) if isinstance(node, dict) else {}
        return node

    def get(self) -> Any:
        return self._node()

    def set(self, value: Any) -> None:
        node = self.state
        for part in self.path[:-1]:
            node = node.setdefault(part, {})
        if self.path:
            node[self.path[-1]] = value

    def child(self, part: str) -> "FakeReference":
        return FakeReference(self.state, self.path + (part,))

    def push(self, value: Any = None) -> "FakeReference":
        children = self._node()
        if isinstance(children, list):
            parent = self.state
            for part in self.path[:-1]:
                parent = parent[part]
            parent[self.path[-1]] = {str(index): value for index, value in enumerate(children)}
            children = self._node()
        key = f"item-{len(children) + 1}"
        reference = self.child(key)
        if value is not None:
            reference.set(value)
        reference.key = key
        return reference


def make_firebase_store(monkeypatch: Any) -> FirebaseDemoStore:
    fake_state: dict[str, Any] = {}
    reference = FakeReference(fake_state, ("demo",))
    firebase_app = object()
    credential_module = type("Credentials", (), {"Certificate": staticmethod(lambda _: object())})
    database_module = type("Database", (), {"reference": staticmethod(lambda *_args, **_kwargs: reference)})
    admin_module = type("Admin", (), {
        "credentials": credential_module,
        "db": database_module,
        "get_app": staticmethod(lambda _name: (_ for _ in ()).throw(ValueError("missing"))),
        "initialize_app": staticmethod(lambda *_args, **_kwargs: firebase_app),
    })
    monkeypatch.setitem(__import__("sys").modules, "firebase_admin", admin_module)
    monkeypatch.setitem(__import__("sys").modules, "firebase_admin.credentials", credential_module)
    monkeypatch.setitem(__import__("sys").modules, "firebase_admin.db", database_module)
    from pathlib import Path
    monkeypatch.setattr(Path, "is_file", lambda _self: True)
    return FirebaseDemoStore("https://example.firebaseio.com", Path("serviceAccountKey.json"))


def test_health_and_dashboard_are_local_demo() -> None:
    client = create_app().test_client()

    health = client.get("/health")
    page = client.get("/")

    assert health.status_code == 200
    assert health.json["mode"] == "memory_demo"
    assert health.json["timezone"] == "Africa/Nairobi"
    assert page.status_code == 200
    assert b"DEMO DATA" in page.data


def test_dashboard_values_are_marked_synthetic() -> None:
    response = create_app().test_client().get("/api/dashboard")

    assert response.status_code == 200
    assert response.json["backend"] == "memory"
    assert response.json["latest"]["synthetic"] is True
    assert len(response.json["records"]) == 24
    assert all(record["synthetic"] for record in response.json["records"])
    assert response.json["currency"] == "KES"


def test_warm_scenario_adds_synthetic_alert() -> None:
    client = create_app().test_client()

    response = client.post("/api/simulate", json={"scenario": "warm"})
    dashboard = client.get("/api/dashboard").json

    assert response.status_code == 200
    assert response.json["reading"]["synthetic"] is True
    assert any(alert["type"] == "Temperature example" for alert in dashboard["alerts"])


def test_unknown_scenario_is_rejected_and_photo_model_is_not_faked() -> None:
    client = create_app().test_client()

    invalid = client.post("/api/simulate", json={"scenario": "unknown"})
    prediction = client.post("/api/predict")

    assert invalid.status_code == 400
    assert prediction.status_code == 503
    assert "not active" in prediction.json["error"]


def test_reset_restores_initial_demo_records() -> None:
    client = create_app().test_client()
    client.post("/api/simulate", json={"scenario": "dry"})

    reset = client.post("/api/demo/reset")
    dashboard = client.get("/api/dashboard").json

    assert reset.status_code == 200
    assert len(dashboard["records"]) == 24
    assert len(dashboard["alerts"]) == 1


def test_firebase_store_seeds_and_reads_demo_records(monkeypatch: Any) -> None:
    store = make_firebase_store(monkeypatch)
    initial = store.get_dashboard()
    store.add_reading({"temperature": 28.2, "humidity": 85.0, "synthetic": True, "timestamp": "2026-11-21T10:00:00+00:00"}, {"type": "Temperature example", "synthetic": True, "timestamp": "2026-11-21T10:00:00+00:00"})

    updated = store.get_dashboard()

    assert len(initial["records"]) == 24
    assert len(updated["records"]) == 25
    assert updated["latest"]["temperature"] == 28.2
    assert updated["alerts"][0]["id"] == "item-2"


def test_local_settings_reload_switches_database_backend(monkeypatch: Any, tmp_path: Any) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DB_BACKEND=memory\n", encoding="utf-8")
    monkeypatch.setattr(app_module, "ENV_FILE", env_file)
    app = create_app()

    class FirebaseLabelledMemoryStore(MemoryDemoStore):
        backend_name = "firebase"

    firebase_store = FirebaseLabelledMemoryStore()
    monkeypatch.setattr(app_module, "_configured_store", lambda: firebase_store)
    env_file.write_text("DB_BACKEND=firebase\n", encoding="utf-8")
    stamp = env_file.stat().st_mtime_ns + 1_000_000_000
    __import__("os").utime(env_file, ns=(stamp, stamp))

    response = app.test_client().get("/api/dashboard")

    assert response.status_code == 200
    assert response.json["backend"] == "firebase"
