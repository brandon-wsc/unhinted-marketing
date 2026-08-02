"""In-memory sliding-window rate limiter for auth endpoints (MVP; Redis later)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from internal.config import settings

# Published example default in .env.example — long enough (≥32) but not a secret.
JWT_SECRET_INSECURE_DEFAULT = "change-me-to-a-long-random-secret-at-least-32-chars"


class SlidingWindowRateLimiter:
    """Per-key sliding window: allow at most `max_requests` in `window_seconds`."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def allow(self, key: str, *, max_requests: int, window_seconds: float) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            q = self._hits[key]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= max_requests:
                return False
            q.append(now)
            return True


_auth_limiter = SlidingWindowRateLimiter()


def get_auth_rate_limiter() -> SlidingWindowRateLimiter:
    return _auth_limiter


def reset_auth_rate_limiter() -> None:
    """Clear counters — used by API tests between cases."""
    _auth_limiter.reset()


def _client_key(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_auth_rate_limit(request: Request, *, bucket: str) -> None:
    """Raise 429 when the client exceeds the configured auth window."""
    if not settings.auth_rate_limit_enabled:
        return
    key = f"{bucket}:{_client_key(request)}"
    ok = _auth_limiter.allow(
        key,
        max_requests=settings.auth_rate_limit_max,
        window_seconds=float(settings.auth_rate_limit_window_seconds),
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many auth requests — try again later",
            headers={"Retry-After": str(settings.auth_rate_limit_window_seconds)},
        )


def jwt_secret_is_insecure(secret: str | None = None) -> bool:
    """True if too short, or equal to the published .env.example default."""
    value = (secret if secret is not None else settings.jwt_secret).strip()
    return len(value) < 32 or value == JWT_SECRET_INSECURE_DEFAULT


def assert_jwt_secret_safe() -> None:
    """Refuse weak / known-default JWT secrets outside development."""
    if settings.allow_insecure_jwt:
        return
    if settings.app_env == "development":
        return
    if jwt_secret_is_insecure():
        raise RuntimeError(
            "JWT_SECRET is missing, shorter than 32 chars, or still the published "
            ".env.example default (not a real secret). Set a unique random value, "
            "or APP_ENV=development / ALLOW_INSECURE_JWT=true for local only."
        )
