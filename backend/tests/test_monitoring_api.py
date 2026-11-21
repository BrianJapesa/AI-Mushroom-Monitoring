"""Coverage for the real monitoring API using isolated in-memory services."""

from __future__ import annotations

import io
import threading
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.app import create_app
from backend.database import MemoryDemoStore
from backend.mushroom.config import Settings
from backend.mushroom.db import MemoryDB, _parts
from backend.mushroom.inference import InferenceService
from backend.mushroom.routes import _valid_bag_id


@pytest.fixture
def context() -> tuple[object, MemoryDB]:
    """Create an API client whose writes never reach the configured Firebase."""
    root = Path(__file__).resolve().parents[2]
    settings = replace(
        Settings.from_env(root / "backend" / ".env", root),
        db_backend="memory",
        firebase_url="",
        api_key="",
        alert_cooldown_seconds=600,
    )
    database = MemoryDB()
    app = create_app(
        store=MemoryDemoStore(),
        database=database,
        settings=settings,
    )
    app.config["TESTING"] = True
    return app.test_client(), database


def test_sensor_validates_and_stores_then_raises_and_recovers(
    context: tuple[object, MemoryDB],
) -> None:
    client, database = context
    invalid = client.post("/sensor", json={"temperature": True, "humidity": 85})
    assert invalid.status_code == 400
    assert invalid.json == {
        "error": "Temperature must be a number between -40 and 85 °C."
    }

    first = client.post("/sensor", json={"temperature": 20.0, "humidity": 85.0})
    second = client.post("/sensor", json={"temperature": 20.2, "humidity": 85.0})
    assert first.status_code == second.status_code == 200
    assert len(first.json["alerts_raised"]) == 1
    assert second.json["alerts_raised"] == []
    assert len(database.query("alerts")) == 1

    recovery = client.post("/sensor", json={"temperature": 23.0, "humidity": 85.0})
    assert recovery.status_code == 200
    assert database.get("sensors/latest")["temperature"] == 23.0
    assert [row["status"] for row in database.query("alerts")] == ["resolved", "open"]


def test_sensor_rejects_out_of_range_and_bad_text(
    context: tuple[object, MemoryDB],
) -> None:
    client, _database = context
    response = client.post(
        "/sensor", json={"temperature": 20, "humidity": 101, "room": "Room 1"}
    )
    assert response.status_code == 400
    response = client.post(
        "/sensor", json={"temperature": 20, "humidity": 85, "room": "x" * 21}
    )
    assert response.status_code == 400


def test_manual_alert_deduplicates_and_resolves(
    context: tuple[object, MemoryDB],
) -> None:
    client, database = context
    payload = {
        "message": "Check Room 1",
        "type": "manual-check",
        "location": "Room 1",
        "level": "high",
    }
    assert client.post("/alert", json=payload).json["status"] == "queued"
    assert client.post("/alert", json=payload).json["status"] == "suppressed"
    stored = database.query("alerts")
    assert len(stored) == 1
    key = next(iter(database.get("alerts")))
    resolved = client.post(f"/alerts/{key}/resolve")
    assert resolved.status_code == 200
    assert resolved.json["status"] == "resolved"
    assert client.post("/alerts/missing/resolve").status_code == 404
    assert client.post("/alerts/bad.id/resolve").status_code == 400
    assert client.get("/alerts?status=open").status_code == 200


def test_records_csv_summary_and_invalid_filters(
    context: tuple[object, MemoryDB],
) -> None:
    client, _database = context
    client.post(
        "/sensor",
        json={
            "temperature": 24.5,
            "humidity": 85,
            "room": "Room 1",
            "device_id": "sensor-1",
        },
    )
    assert client.get("/records?limit=0").status_code == 400
    assert client.get("/records?since=not-a-date").status_code == 400
    assert (
        client.get("/records?room=Room%201&since=2020-01-01T00:00:00Z").status_code
        == 200
    )
    assert (
        client.get("/records?room=room-with-a-name-that-is-too-long").status_code == 400
    )
    assert client.get("/records").json[0]["device_id"] == "sensor-1"
    assert b"temperature_c" in client.get("/records/export.csv").data
    summary = client.get("/stats/summary?hours=24")
    assert summary.status_code == 200
    assert summary.json["temperature"]["avg"] == 24.5


def test_health_and_api_key_authentication() -> None:
    root = Path(__file__).resolve().parents[2]
    settings = replace(
        Settings.from_env(root / "backend" / ".env", root),
        db_backend="memory",
        firebase_url="",
        api_key="test-api-key-value",
    )
    app = create_app(store=MemoryDemoStore(), database=MemoryDB(), settings=settings)
    client = app.test_client()
    assert client.get("/health").json["auth_required"] is True
    assert client.get("/health").json["sms_enabled"] is False
    assert client.get("/health").json["email_enabled"] is False
    assert client.get("/records").status_code == 401
    assert client.get("/records", headers={"X-API-Key": "wrong"}).status_code == 401
    assert (
        client.get("/records", headers={"X-API-Key": "test-api-key-value"}).status_code
        == 200
    )


@pytest.mark.parametrize("path", ["a.b", "a$b", "a#b", "a[b", "a]b"])
def test_firebase_key_characters_are_rejected(path: str) -> None:
    with pytest.raises(ValueError):
        _parts(path)


def test_slash_is_rejected_inside_external_bag_id() -> None:
    assert _valid_bag_id("bag/other") is None


def test_unknown_route_returns_json(context: tuple[object, MemoryDB]) -> None:
    client, _database = context
    response = client.get("/missing")
    assert response.status_code == 404
    assert response.json == {"error": "This page or service was not found."}


def test_sensor_latest_alert_filters_bag_routes_and_bad_inputs(
    context: tuple[object, MemoryDB],
) -> None:
    client, database = context
    assert client.get("/sensors/latest").json == {}
    assert client.get("/alerts?limit=invalid").status_code == 400
    assert client.get("/alerts?status=unknown").status_code == 400
    assert client.get("/bags/not%2Fvalid/history").status_code == 404
    assert client.get("/bags/bag-1/history").json == []
    assert client.get("/bags").json == []
    database.set(
        "bags/bag-1",
        {"id": "bag-1", "status": "healthy", "timestamp": "2026-11-21T00:00:00+00:00"},
    )
    assert client.get("/bags").json[0]["id"] == "bag-1"
    assert client.get("/stats/summary?hours=721").status_code == 400
    assert client.get("/stats/summary?hours=bad").status_code == 400


def test_finite_number_and_memory_database_operations() -> None:
    database = MemoryDB()
    database.set("records/one", {"timestamp": "2026-01-01T00:00:00+00:00", "v": 1})
    database.push("records", {"timestamp": "2026-01-02T00:00:00+00:00", "v": 2})
    assert database.query("records", 1)[0]["v"] == 2
    database.delete("records/one")
    assert [row["v"] for row in database.query("records")] == [2]
    with pytest.raises(TypeError):
        database.set("records/local-00000001/v/child", 3)
    assert client_finite_numbers()


def test_record_filter_bad_room_and_bad_stored_timestamps() -> None:
    from backend.mushroom.routes import _record_filters, _timestamp_or_oldest

    root = Path(__file__).resolve().parents[2]
    settings = replace(
        Settings.from_env(root / "backend" / ".env", root),
        db_backend="memory",
        firebase_url="",
        api_key="",
    )
    app = create_app(store=MemoryDemoStore(), database=MemoryDB(), settings=settings)
    with app.test_request_context("/records?room=%01"):
        assert _record_filters([{"room": "Room 1"}]) == []
    with app.test_request_context("/records?since=broken-date"):
        assert _record_filters([{"timestamp": "bad"}]) == []
    assert _timestamp_or_oldest(None).year == 1970


def client_finite_numbers() -> bool:
    """Exercise type and finite-number input checks used by sensor validation."""
    from backend.mushroom.security import finite_number

    return all(
        (
            finite_number(1),
            finite_number(1.2),
            not finite_number(True),
            not finite_number(float("nan")),
            not finite_number(float("inf")),
            not finite_number("1"),
        )
    )


class PredictionStub:
    """Test-only model adapter that returns a fixed, non-farm classification."""

    loaded = True
    version = "test-model"
    synthetic = True

    def __init__(self) -> None:
        self.status = "contaminated"

    def predict(self, _image_bytes: bytes) -> dict[str, object]:
        return {
            "status": self.status,
            "confidence": 0.9,
            "probabilities": {"healthy": 0.02, "suspect": 0.08, "contaminated": 0.9},
            "uncertain": False,
            "model_version": "test-model",
            "model_synthetic": True,
        }


class ModelOutputStub:
    """Stub Keras-like model that returns probabilities for inference tests."""

    def predict(self, _batch: np.ndarray, verbose: int = 0) -> np.ndarray:
        del verbose
        return np.asarray([[0.02, 0.08, 0.9]], dtype=np.float32)


def make_jpeg() -> bytes:
    """Encode a small valid test fixture in memory without writing farm photos."""
    ok, encoded = cv2.imencode(".jpg", np.zeros((64, 64, 3), dtype=np.uint8))
    assert ok
    return encoded.tobytes()


def test_prediction_upload_validation_and_contamination_history() -> None:
    root = Path(__file__).resolve().parents[2]
    settings = replace(
        Settings.from_env(root / "backend" / ".env", root),
        db_backend="memory",
        firebase_url="",
        api_key="",
    )
    database = MemoryDB()
    model = PredictionStub()
    app = create_app(
        store=MemoryDemoStore(), database=database, settings=settings, inference=model
    )  # type: ignore[arg-type]
    client = app.test_client()
    assert client.post("/predict").status_code == 415
    assert (
        client.post(
            "/predict", data={"image": (io.BytesIO(b"bad"), "photo.jpg", "image/jpeg")}
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/predict",
            data={"image": (io.BytesIO(make_jpeg()), "photo.txt", "text/plain")},
        ).status_code
        == 415
    )
    result = client.post(
        "/predict",
        data={
            "image": (io.BytesIO(make_jpeg()), "photo.jpg", "image/jpeg"),
            "bag_id": "bag-1",
            "room": "Room 1",
        },
    )
    assert result.status_code == 200
    assert result.json["status"] == "contaminated"
    assert client.get("/bags/bag-1/history").json[0]["model_synthetic"] is True
    assert len(database.query("alerts")) == 1
    assert (
        client.post(
            "/predict",
            data={
                "image": (io.BytesIO(make_jpeg()), "photo.jpg", "image/jpeg"),
                "bag_id": "bad/id",
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/predict",
            data={
                "image": (io.BytesIO(make_jpeg()), "photo.jpg", "image/jpeg"),
                "bag_id": "bag-1",
                "room": "x" * 21,
            },
        ).status_code
        == 400
    )
    assert client.get("/bags/bag-1/history?limit=0").status_code == 400
    model.status = "healthy"
    recovered = client.post(
        "/predict",
        data={
            "image": (io.BytesIO(make_jpeg()), "photo.jpg", "image/jpeg"),
            "bag_id": "bag-1",
            "room": "Room 1",
        },
    )
    assert recovered.status_code == 200
    assert len(database.query("alerts")) == 2


def test_unready_model_returns_service_unavailable() -> None:
    root = Path(__file__).resolve().parents[2]
    settings = replace(
        Settings.from_env(root / "backend" / ".env", root),
        db_backend="memory",
        firebase_url="",
        api_key="",
    )
    app = create_app(store=MemoryDemoStore(), database=MemoryDB(), settings=settings)
    client = app.test_client()
    response = client.post(
        "/predict", data={"image": (io.BytesIO(make_jpeg()), "photo.jpg", "image/jpeg")}
    )
    assert response.status_code == 503


def test_predict_rejects_bad_content_and_upload_size() -> None:
    root = Path(__file__).resolve().parents[2]
    settings = replace(
        Settings.from_env(root / "backend" / ".env", root),
        db_backend="memory",
        firebase_url="",
        api_key="",
        max_upload_bytes=2048,
    )
    app = create_app(
        store=MemoryDemoStore(),
        database=MemoryDB(),
        settings=settings,
        inference=PredictionStub(),
    )  # type: ignore[arg-type]
    client = app.test_client()
    assert (
        client.post(
            "/predict", data={"image": (io.BytesIO(b"bad"), "photo.jpg", "image/jpeg")}
        ).status_code
        == 415
    )
    oversized = client.post(
        "/predict", data={"image": (io.BytesIO(b"x" * 3000), "photo.jpg", "image/jpeg")}
    )
    assert oversized.status_code == 413


def test_inference_preprocessing_and_metadata_rejection(tmp_path: Path) -> None:
    metadata = tmp_path / "model_meta.json"
    service = InferenceService(tmp_path / "missing.keras", metadata)
    assert service.loaded is False
    with pytest.raises(RuntimeError):
        service.predict(b"image")
    service.model = ModelOutputStub()
    service._lock = threading.Lock()
    output = service.predict(make_jpeg())
    assert output["status"] == "contaminated"
    with pytest.raises(ValueError, match="not a readable image"):
        service.predict(b"not-an-image")
    with pytest.raises(ValueError, match="64 by 64"):
        ok, tiny = cv2.imencode(".jpg", np.zeros((16, 16, 3), dtype=np.uint8))
        assert ok
        service.predict(tiny.tobytes())
    metadata.write_text('{"classes":["wrong"]}', encoding="utf-8")
    with pytest.raises(ValueError, match="class order"):
        (tmp_path / "model.keras").write_bytes(b"placeholder model file")
        InferenceService(tmp_path / "model.keras", metadata)
