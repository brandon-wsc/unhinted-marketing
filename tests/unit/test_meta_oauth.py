"""Meta OAuth connect flow (ADR 0022 OAuth slice) — mocked repos + Graph; no DB."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

from internal import config
from internal.auth.meta_oauth import (
    MetaOAuthError,
    _oauth_fields,
    exchange_code,
    parse_state,
    start_oauth,
)
from internal.memory.models import SocialAccount

IG_USER = "17841400000000"


class ScriptedClient:
    def __init__(self, token_payload: dict, me_payload: dict | None = None) -> None:
        self._token_payload = token_payload
        self._me_payload = me_payload or {}
        self.get_urls: list[str] = []
        self.params_log: list[dict] = []

    async def __aenter__(self) -> ScriptedClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, params: dict | None = None):
        import httpx

        self.get_urls.append(url)
        self.params_log.append(params or {})
        if "/oauth/access_token" in url:
            return httpx.Response(200, json=self._token_payload)
        return httpx.Response(200, json=self._me_payload)


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    kek = Fernet.generate_key().decode()
    monkeypatch.setattr(config.settings, "byok_encryption_key", kek)
    monkeypatch.setattr(config.settings, "meta_app_id", "123456")
    monkeypatch.setattr(config.settings, "meta_app_secret", "secret123")
    monkeypatch.setattr(
        config.settings,
        "meta_oauth_redirect_uri",
        "http://localhost:8000/api/social/oauth/callback",
    )


def _account() -> SocialAccount:
    return SocialAccount(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        platform="instagram",
        ig_user_id="",
        access_token_encrypted="",
        token_last4="",
        created_by=None,
        oauth_connect_state=None,
        oauth_pending_scopes=None,
    )


async def test_start_oauth_url_and_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    company_id = uuid.uuid4()
    db = AsyncMock()
    row = _account()
    # placeholder-row constructor needs flush on the instance; model rows get
    # `.flush` from the session, so give this one a no-op via the instance.
    from internal.auth import meta_oauth as mod

    async def fake_get(*a, **k):
        return row

    monkeypatch.setattr(mod.repos, "get_social_account", fake_get)
    row.flush = AsyncMock()  # type: ignore[attr-defined]

    started = await start_oauth(db, company_id=company_id)
    assert started.authorization_url.startswith(
        "https://www.facebook.com/v22.0/dialog/oauth?"
    )
    from urllib.parse import parse_qs, urlsplit

    state_param = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    parsed = parse_state(state_param)
    assert parsed is not None
    row_id, blob = parsed
    assert str(row.id) == row_id
    assert row.oauth_connect_state == blob
    assert row.oauth_connect_state == started.connect_state


async def test_oauth_fields_require_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr(config.settings, "meta_app_id", None)
    with pytest.raises(MetaOAuthError):
        _oauth_fields()


async def test_exchange_code_success_sets_account(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    from internal.auth import meta_oauth as mod

    row = _account()
    monkeypatch.setattr(mod.repos, "get_social_account", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.repos, "get_social_account_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(
        mod.repos,
        "upsert_social_account",
        AsyncMock(return_value=row),
    )
    client = ScriptedClient(
        token_payload={
            "access_token": "IGQW-token-12345",
            "expires_in": 5_184_000,
            "token_type": "bearer",
            "granted_scopes": [
                "instagram_basic",
                "instagram_content_publish",
                "pages_show_list",
            ],
        },
        me_payload={"id": "fbid-1", "instagram_business_account": {"id": IG_USER}},
    )
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: client)

    db = AsyncMock()
    db.flush = AsyncMock()

    # establish pending state on the row like start_oauth does
    started = await start_oauth(db, company_id=row.company_id)
    row.oauth_connect_state = started.connect_state

    result = await exchange_code(
        db, code="auth-code", state=f"{row.id}:{started.connect_state}", csrf_token=started.csrf_token
    )
    assert result.ig_user_id == IG_USER
    assert result.fb_user_id == "fbid-1"
    assert result.missing_scopes == []
    assert row.oauth_connect_state is None
    assert mod.repos.upsert_social_account.await_count == 1
    call = mod.repos.upsert_social_account.await_args.kwargs
    assert call["ig_user_id"] == IG_USER
    assert call["token_last4"] == "2345"


async def test_exchange_code_reports_missing_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    from internal.auth import meta_oauth as mod

    row = _account()
    monkeypatch.setattr(mod.repos, "get_social_account", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.repos, "get_social_account_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.repos, "upsert_social_account", AsyncMock(return_value=row))
    client = ScriptedClient(
        token_payload={
            "access_token": "IGQW-token-12345",
            "expires_in": 3600,
            "granted_scopes": ["instagram_basic"],
        },
        me_payload={"id": "fbid-1", "instagram_business_account": {"id": IG_USER}},
    )
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: client)

    db = AsyncMock()
    db.flush = AsyncMock()
    started = await start_oauth(db, company_id=row.company_id)
    row.oauth_connect_state = started.connect_state

    result = await exchange_code(
        db, code="code", state=f"{row.id}:{started.connect_state}", csrf_token=started.csrf_token
    )
    assert result.missing_scopes == ["instagram_content_publish", "pages_show_list"]


async def test_pending_connect_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    from datetime import UTC, datetime, timedelta

    from internal.auth.meta_oauth import (
        OAUTH_PENDING_TTL,
        _encrypt_connect_state,
        pending_connect_is_stale,
    )

    blob = _encrypt_connect_state("row", "verifier", "csrf")
    assert pending_connect_is_stale(blob) is False
    later = datetime.now(UTC) + OAUTH_PENDING_TTL + timedelta(seconds=1)
    assert pending_connect_is_stale(blob, now=later) is True
    assert pending_connect_is_stale("not-a-blob") is True


async def test_exchange_code_rejects_stale_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    from internal.auth import meta_oauth as mod

    monkeypatch.setattr(mod.repos, "get_social_account_by_id", AsyncMock(return_value=None))
    db = AsyncMock()
    with pytest.raises(MetaOAuthError):
        await exchange_code(db, code="code", state="bogus:state", csrf_token="x")
