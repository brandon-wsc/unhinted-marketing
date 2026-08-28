"""Unit tests for Cloudflare Turnstile verification."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from internal.auth import turnstile as turnstile_mod
from internal.config import settings


@pytest.fixture(autouse=True)
def _reset_turnstile_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "turnstile_enabled", False)
    monkeypatch.setattr(settings, "turnstile_secret_key", None)


def test_turnstile_required_false_when_disabled() -> None:
    assert turnstile_mod.turnstile_required() is False


def test_turnstile_required_true_when_enabled_with_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "turnstile_enabled", True)
    monkeypatch.setattr(settings, "turnstile_secret_key", "secret-key")
    assert turnstile_mod.turnstile_required() is True


@pytest.mark.asyncio
async def test_enforce_turnstile_skips_when_disabled() -> None:
    request = MagicMock()
    await turnstile_mod.enforce_turnstile(request, None)


@pytest.mark.asyncio
async def test_enforce_turnstile_requires_token_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "turnstile_enabled", True)
    monkeypatch.setattr(settings, "turnstile_secret_key", "secret-key")
    request = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await turnstile_mod.enforce_turnstile(request, None)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_enforce_turnstile_accepts_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "turnstile_enabled", True)
    monkeypatch.setattr(settings, "turnstile_secret_key", "secret-key")
    request = MagicMock()
    request.client = MagicMock(host="203.0.113.1")

    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("internal.auth.turnstile.httpx.AsyncClient", return_value=mock_client):
        await turnstile_mod.enforce_turnstile(request, "valid-token")

    mock_client.post.assert_awaited_once()
    call_kwargs = mock_client.post.await_args
    assert call_kwargs.args[0] == turnstile_mod.TURNSTILE_VERIFY_URL
    assert call_kwargs.kwargs["data"]["response"] == "valid-token"


@pytest.mark.asyncio
async def test_enforce_turnstile_rejects_failed_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "turnstile_enabled", True)
    monkeypatch.setattr(settings, "turnstile_secret_key", "secret-key")
    request = MagicMock()
    request.client = None

    mock_response = MagicMock()
    mock_response.json.return_value = {"success": False, "error-codes": ["invalid-input-response"]}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("internal.auth.turnstile.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(HTTPException) as exc:
            await turnstile_mod.enforce_turnstile(request, "bad-token")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_enforce_turnstile_handles_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "turnstile_enabled", True)
    monkeypatch.setattr(settings, "turnstile_secret_key", "secret-key")
    request = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.RequestError("network"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("internal.auth.turnstile.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(HTTPException) as exc:
            await turnstile_mod.enforce_turnstile(request, "token")
    assert exc.value.status_code == 503
