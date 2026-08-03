"""Unit tests for auth rate limiter + JWT secret guard."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from internal.auth.rate_limit import (
    JWT_SECRET_INSECURE_DEFAULT,
    SlidingWindowRateLimiter,
    assert_jwt_secret_safe,
    enforce_auth_rate_limit,
    jwt_secret_is_insecure,
    reset_auth_rate_limiter,
)


def test_sliding_window_allows_then_blocks() -> None:
    limiter = SlidingWindowRateLimiter()
    assert limiter.allow("k", max_requests=2, window_seconds=60.0)
    assert limiter.allow("k", max_requests=2, window_seconds=60.0)
    assert not limiter.allow("k", max_requests=2, window_seconds=60.0)


def test_sliding_window_separate_keys() -> None:
    limiter = SlidingWindowRateLimiter()
    assert limiter.allow("a", max_requests=1, window_seconds=60.0)
    assert limiter.allow("b", max_requests=1, window_seconds=60.0)
    assert not limiter.allow("a", max_requests=1, window_seconds=60.0)


def test_jwt_secret_is_insecure() -> None:
    # Example default is long enough but publicly known → insecure.
    assert len(JWT_SECRET_INSECURE_DEFAULT) >= 32
    assert jwt_secret_is_insecure(JWT_SECRET_INSECURE_DEFAULT)
    assert jwt_secret_is_insecure("short")
    assert not jwt_secret_is_insecure("a" * 32)


def test_assert_jwt_secret_safe_production(monkeypatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "app_env", "production")
    monkeypatch.setattr(config.settings, "allow_insecure_jwt", False)
    monkeypatch.setattr(config.settings, "jwt_secret", JWT_SECRET_INSECURE_DEFAULT)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        assert_jwt_secret_safe()

    monkeypatch.setattr(config.settings, "jwt_secret", "x" * 40)
    assert_jwt_secret_safe()  # does not raise

    monkeypatch.setattr(config.settings, "jwt_secret", JWT_SECRET_INSECURE_DEFAULT)
    monkeypatch.setattr(config.settings, "allow_insecure_jwt", True)
    assert_jwt_secret_safe()


def test_enforce_auth_rate_limit(monkeypatch) -> None:
    from internal import config

    reset_auth_rate_limiter()
    monkeypatch.setattr(config.settings, "auth_rate_limit_enabled", True)
    monkeypatch.setattr(config.settings, "auth_rate_limit_max", 2)
    monkeypatch.setattr(config.settings, "auth_rate_limit_window_seconds", 60)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/auth/login",
        "raw_path": b"/api/auth/login",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    request = Request(scope)

    enforce_auth_rate_limit(request, bucket="login")
    enforce_auth_rate_limit(request, bucket="login")
    with pytest.raises(HTTPException) as exc:
        enforce_auth_rate_limit(request, bucket="login")
    assert exc.value.status_code == 429
    reset_auth_rate_limiter()
