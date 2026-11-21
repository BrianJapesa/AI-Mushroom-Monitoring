"""API authentication, CORS, request limits, and input validation helpers."""

from __future__ import annotations

import hmac
import math
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any

from flask import jsonify, request


class Security:
    """Apply optional API-key checks and bounded per-client request limits."""

    def __init__(
        self,
        api_key: str,
        allowed_origins: tuple[str, ...],
        clock: Any = time.monotonic,
    ) -> None:
        self.api_key = api_key
        self.allowed_origins = allowed_origins
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def before_request(self) -> Any:
        """Reject unauthenticated API calls and excessive traffic without leaking keys."""
        if request.path in {"/", "/health"}:
            return None
        if self.api_key:
            supplied = request.headers.get("X-API-Key", "")
            if not supplied or not hmac.compare_digest(supplied, self.api_key):
                return jsonify({"error": "API key is missing or incorrect."}), 401
        limit = 10 if request.path in {"/predict", "/api/predict"} else 60
        identity = request.headers.get("X-API-Key") or request.remote_addr or "local"
        if not self._allow(f"{request.path}:{identity}", limit):
            return jsonify(
                {"error": "Too many requests. Wait a minute and try again."}
            ), 429
        origin = request.headers.get("Origin")
        if origin and self.allowed_origins and origin not in self.allowed_origins:
            return jsonify(
                {"error": "This website is not allowed to use the monitoring service."}
            ), 403
        return None

    def _allow(self, key: str, limit: int) -> bool:
        """Keep only recent request times for a key/IP bucket."""
        now = self._clock()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] >= 60:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True

    def cors_headers(self, response: Any) -> Any:
        """Attach an explicit CORS origin only when it is configured."""
        origin = request.headers.get("Origin")
        if origin and origin in self.allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    @staticmethod
    def security_headers(response: Any) -> Any:
        """Add browser security headers to every response."""
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'"
        )
        return response


def finite_number(value: Any) -> bool:
    """Return true only for finite JSON numbers, excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def clean_text(value: Any, limit: int, allow_empty: bool = False) -> str | None:
    """Validate a short printable string and trim surrounding whitespace."""
    if not isinstance(value, str):
        return None
    result = value.strip()
    if (
        (not result and not allow_empty)
        or len(result) > limit
        or any(ord(char) < 32 for char in result)
    ):
        return None
    return result
