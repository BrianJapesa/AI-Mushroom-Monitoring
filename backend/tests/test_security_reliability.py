"""Focused tests for request limits, origin policy, and browser headers."""

from __future__ import annotations

from flask import Flask, Response

from backend.mushroom.security import Security, clean_text, finite_number


class FakeClock:
    """Monotonic test clock for deterministic request-limit windows."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def test_rate_limits_are_path_scoped_and_expire_after_one_minute() -> None:
    app = Flask(__name__)
    clock = FakeClock()
    security = Security("", (), clock)

    with app.test_request_context("/admin/test-notification"):
        assert security.before_request() is None
        assert security.before_request() is None
        limited = security.before_request()
        assert limited is not None
        assert limited[1] == 429

    with app.test_request_context("/predict"):
        for _ in range(10):
            assert security.before_request() is None
        assert security.before_request()[1] == 429

    clock.value = 60.0
    with app.test_request_context("/admin/test-notification"):
        assert security.before_request() is None


def test_origin_policy_and_security_headers() -> None:
    app = Flask(__name__)
    security = Security("test-only-key", ("https://dashboard.example.test",))

    with app.test_request_context(
        "/records",
        headers={"X-API-Key": "test-only-key", "Origin": "https://other.example.test"},
    ):
        denied = security.before_request()
        assert denied is not None
        assert denied[1] == 403

    with app.test_request_context(
        "/records", headers={"Origin": "https://dashboard.example.test"}
    ):
        response = security.cors_headers(Response())
        assert response.headers["Access-Control-Allow-Origin"] == (
            "https://dashboard.example.test"
        )
        assert response.headers["Vary"] == "Origin"
        secured = security.security_headers(response)
        assert secured.headers["X-Content-Type-Options"] == "nosniff"
        assert secured.headers["X-Frame-Options"] == "DENY"


def test_input_helpers_reject_non_finite_numbers_and_control_text() -> None:
    assert finite_number(2.5)
    assert not finite_number(True)
    assert not finite_number(float("nan"))
    assert clean_text("  Room 1  ", 20) == "Room 1"
    assert clean_text("line\nbreak", 20) is None
    assert clean_text("", 20) is None
