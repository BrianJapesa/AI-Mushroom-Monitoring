"""Application package for the oyster-mushroom monitoring API."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from .alerts import AlertEngine
from .config import Settings
from .db import Database, DatabaseUnavailable, FirebaseDB, MemoryDB
from .inference import InferenceService
from .routes import api
from .security import Security

LOGGER = logging.getLogger(__name__)
VERSION = "1.0.0"


def create_monitoring_app(
    root: Path,
    settings: Settings | None = None,
    database: Database | None = None,
    inference: InferenceService | None = None,
    app: Flask | None = None,
) -> Flask:
    """Build the secure API services and injectable dependencies for a run or test."""
    settings = settings or Settings.from_env(root / "backend" / ".env", root)
    if database is None:
        try:
            database = (
                MemoryDB()
                if settings.db_backend == "memory"
                else FirebaseDB(
                    settings.firebase_url, str(settings.firebase_credentials)
                )
            )
        except (FileNotFoundError, ValueError, OSError, ImportError):
            LOGGER.warning(
                "Monitoring database is not ready; database routes will return a service error"
            )
            database = UnavailableDB()
    inference = inference or InferenceService(
        root / "backend" / "models" / "contamination_model.keras",
        root / "backend" / "models" / "model_meta.json",
        settings.min_confidence,
    )
    alerts = AlertEngine(database, settings)
    security = Security(settings.api_key, settings.cors_origins)

    app = app or Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = settings.max_upload_bytes
    app.extensions["mushroom"] = {
        "db": database,
        "settings": settings,
        "inference": inference,
        "alerts": alerts,
        "started_at": time.monotonic(),
    }
    app.register_blueprint(api)

    @app.before_request
    def protect_api() -> Any:
        """Protect API endpoints and allow browser preflight requests."""
        if request.method == "OPTIONS":
            return ("", 204)
        return security.before_request()

    @app.after_request
    def add_response_headers(response: Any) -> Any:
        """Add configured CORS and browser security headers."""
        return security.security_headers(security.cors_headers(response))

    @app.errorhandler(413)
    def upload_too_large(_: Exception) -> Any:
        return jsonify(
            {"error": "That file is too large. Choose a smaller photo."}
        ), 413

    @app.errorhandler(404)
    def not_found(_: Exception) -> Any:
        return jsonify({"error": "This page or service was not found."}), 404

    @app.errorhandler(DatabaseUnavailable)
    def database_unavailable(_: DatabaseUnavailable) -> Any:
        """Return a safe retry message when the configured provider is offline."""
        return jsonify(
            {"error": "The database is temporarily unavailable. Try again shortly."}
        ), 503

    @app.errorhandler(500)
    def server_error(_: Exception) -> Any:
        LOGGER.exception("Unhandled monitoring service error")
        return jsonify(
            {"error": "The monitoring service had a problem. Try again."}
        ), 500

    return app


__all__ = ["create_monitoring_app"]


class UnavailableDB:
    """Fail database operations clearly while allowing health and UI to start."""

    name = "unavailable"

    @staticmethod
    def _fail(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("Database is not available.")

    get = _fail
    set = _fail
    push = _fail
    delete = _fail
    query = _fail
