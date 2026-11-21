"""Checks for the synthetic Kenyan-context prototype API."""
from backend.app import create_app


def test_health_and_dashboard_are_local_demo() -> None:
    client = create_app().test_client()

    health = client.get("/health")
    page = client.get("/")

    assert health.status_code == 200
    assert health.json["mode"] == "synthetic_demo"
    assert health.json["timezone"] == "Africa/Nairobi"
    assert page.status_code == 200
    assert b"DEMO DATA" in page.data


def test_dashboard_values_are_marked_synthetic() -> None:
    response = create_app().test_client().get("/api/dashboard")

    assert response.status_code == 200
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
