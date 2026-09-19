"""Instagram Login connect flow (ADR 0022 OAuth slice) — mocked repos + Graph; no DB."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

from internal import config
from internal.auth.meta_oauth import (
    META_OAUTH_SCOPES,
    MetaOAuthError,
    _oauth_fields,
    exchange_code,
    oauth_callback_url,
    oauth_configured,
    parse_state,
    start_oauth,
)
from internal.instance.config import reset_snapshot_cache
from internal.memory.models import SocialAccount

OAUTH_ORIGIN = "https://unhinted.localhost:5173"

IG_USER = "17841400000000"


class ScriptedClient:
    def __init__(
        self,
        token_payload: dict,
        long_lived_payload: dict | None = None,
        me_payload: dict | None = None,
    ) -> None:
        self._token_payload = token_payload
        self._long_lived_payload = long_lived_payload or {
            "access_token": "IGQW-long-lived-12345",
            "token_type": "bearer",
            "expires_in": 5_184_000,
        }
        self._me_payload = me_payload or {}
        self.get_urls: list[str] = []
        self.post_urls: list[str] = []
        self.post_data: list[dict] = []

    async def __aenter__(self) -> ScriptedClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, data: dict | None = None):
        import httpx

        self.post_urls.append(url)
        if data is not None:
            self.post_data.append(data)
        if "api.instagram.com/oauth/access_token" in url:
            return httpx.Response(200, json=self._token_payload)
        return httpx.Response(404, json={})

    async def get(self, url: str, params: dict | None = None):
        import httpx

        self.get_urls.append(url)
        if url.startswith("https://graph.instagram.com/access_token"):
            return httpx.Response(200, json=self._long_lived_payload)
        if url.rstrip("/").endswith("/me"):
            return httpx.Response(200, json=self._me_payload)
        return httpx.Response(200, json={})


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    kek = Fernet.generate_key().decode()
    monkeypatch.setattr(config.settings, "byok_encryption_key", kek)
    monkeypatch.setattr(config.settings, "meta_app_id", "123456")
    monkeypatch.setattr(config.settings, "meta_app_secret", "secret123")
    monkeypatch.setattr(config.settings, "web_base_url", OAUTH_ORIGIN)
    reset_snapshot_cache()


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
    )


def _ok_short_token() -> dict:
    return {
        "access_token": "IGQW-short",
        "user_id": IG_USER,
        "permissions": META_OAUTH_SCOPES,
    }


async def test_start_oauth_url_and_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    company_id = uuid.uuid4()
    db = AsyncMock()
    row = _account()
    from internal.auth import meta_oauth as mod

    async def fake_get(*a, **k):
        return row

    monkeypatch.setattr(mod.repos, "get_social_account", fake_get)

    started = await start_oauth(db, company_id=company_id)
    assert started.authorization_url.startswith("https://www.instagram.com/oauth/authorize?")
    from urllib.parse import parse_qs, urlsplit

    query = parse_qs(urlsplit(started.authorization_url).query)
    assert query["scope"][0] == META_OAUTH_SCOPES
    assert query["redirect_uri"][0] == f"{OAUTH_ORIGIN}/api/social/oauth/callback"
    assert "extras" not in query
    assert "code_challenge" not in query
    assert "auth_type" not in query
    state_param = query["state"][0]
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


async def test_oauth_fields_require_web_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr(config.settings, "web_base_url", "")
    reset_snapshot_cache()
    with pytest.raises(MetaOAuthError):
        _oauth_fields()


async def test_exchange_code_success_sets_account(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    from internal.auth import meta_oauth as mod

    row = _account()
    monkeypatch.setattr(mod.repos, "get_social_account", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.repos, "get_social_account_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.repos, "upsert_social_account", AsyncMock(return_value=row))
    client = ScriptedClient(
        token_payload=_ok_short_token(),
        me_payload={"user_id": IG_USER, "id": "app-scoped", "account_type": "BUSINESS"},
    )
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: client)

    db = AsyncMock()
    db.flush = AsyncMock()

    started = await start_oauth(db, company_id=row.company_id)
    row.oauth_connect_state = started.connect_state

    result = await exchange_code(
        db, code="auth-code", state=f"{row.id}:{started.connect_state}", csrf_token=started.csrf_token
    )
    assert result.ig_user_id == IG_USER
    assert result.missing_scopes == []
    assert row.oauth_connect_state is None
    assert mod.repos.upsert_social_account.await_count == 1
    call = mod.repos.upsert_social_account.await_args.kwargs
    assert call["ig_user_id"] == IG_USER
    assert call["token_last4"] == "2345"
    assert any("api.instagram.com/oauth/access_token" in url for url in client.post_urls)
    assert any(url.startswith("https://graph.instagram.com/access_token") for url in client.get_urls)
    assert any(url.rstrip("/").endswith("/me") for url in client.get_urls)
    assert not any("/me/accounts" in url for url in client.get_urls)


async def test_exchange_code_uses_authorize_time_redirect_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mid-flow web_base_url edit must not change the exchange redirect_uri —
    Meta requires it to equal the authorize-time value."""
    _configure(monkeypatch)
    from internal.auth import meta_oauth as mod

    row = _account()
    monkeypatch.setattr(mod.repos, "get_social_account", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.repos, "get_social_account_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.repos, "upsert_social_account", AsyncMock(return_value=row))
    client = ScriptedClient(
        token_payload=_ok_short_token(),
        me_payload={"user_id": IG_USER, "id": "app-scoped", "account_type": "BUSINESS"},
    )
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: client)
    db = AsyncMock()
    db.flush = AsyncMock()

    started = await start_oauth(db, company_id=row.company_id)
    row.oauth_connect_state = started.connect_state
    monkeypatch.setattr(config.settings, "web_base_url", "https://moved.example")
    reset_snapshot_cache()

    result = await exchange_code(
        db, code="auth-code", state=f"{row.id}:{started.connect_state}", csrf_token=started.csrf_token
    )
    assert result.ig_user_id == IG_USER
    assert client.post_data[0]["redirect_uri"] == f"{OAUTH_ORIGIN}/api/social/oauth/callback"


async def test_exchange_code_prefers_user_id_over_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    from internal.auth import meta_oauth as mod

    row = _account()
    monkeypatch.setattr(mod.repos, "get_social_account", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.repos, "get_social_account_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.repos, "upsert_social_account", AsyncMock(return_value=row))
    client = ScriptedClient(
        token_payload=_ok_short_token(),
        me_payload={"user_id": IG_USER, "id": "wrong-app-scoped", "account_type": "MEDIA_CREATOR"},
    )
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: client)
    db = AsyncMock()
    db.flush = AsyncMock()
    started = await start_oauth(db, company_id=row.company_id)
    row.oauth_connect_state = started.connect_state
    result = await exchange_code(
        db, code="auth-code", state=f"{row.id}:{started.connect_state}", csrf_token=started.csrf_token
    )
    assert result.ig_user_id == IG_USER


async def test_exchange_code_falls_back_to_me_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR 0022: ig_user_id is GET /me user_id, else /me id — not the short-lived user_id."""
    _configure(monkeypatch)
    from internal.auth import meta_oauth as mod

    row = _account()
    monkeypatch.setattr(mod.repos, "get_social_account", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.repos, "get_social_account_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.repos, "upsert_social_account", AsyncMock(return_value=row))
    client = ScriptedClient(
        token_payload={
            "access_token": "IGQW-short",
            "user_id": "short-lived-other",
            "permissions": META_OAUTH_SCOPES,
        },
        me_payload={"id": IG_USER, "account_type": "BUSINESS"},
    )
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: client)
    db = AsyncMock()
    db.flush = AsyncMock()
    started = await start_oauth(db, company_id=row.company_id)
    row.oauth_connect_state = started.connect_state
    result = await exchange_code(
        db,
        code="auth-code",
        state=f"{row.id}:{started.connect_state}",
        csrf_token=started.csrf_token,
    )
    assert result.ig_user_id == IG_USER


async def test_exchange_code_not_professional(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    from internal.auth import meta_oauth as mod

    row = _account()
    monkeypatch.setattr(mod.repos, "get_social_account", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.repos, "get_social_account_by_id", AsyncMock(return_value=row))
    client = ScriptedClient(
        token_payload=_ok_short_token(),
        me_payload={"id": "personal-1", "account_type": "PERSONAL"},
    )
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: client)
    db = AsyncMock()
    started = await start_oauth(db, company_id=row.company_id)
    row.oauth_connect_state = started.connect_state
    with pytest.raises(MetaOAuthError, match="meta_oauth_not_professional"):
        await exchange_code(
            db,
            code="auth-code",
            state=f"{row.id}:{started.connect_state}",
            csrf_token=started.csrf_token,
        )


async def test_exchange_code_missing_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    from internal.auth import meta_oauth as mod

    row = _account()
    monkeypatch.setattr(mod.repos, "get_social_account", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.repos, "get_social_account_by_id", AsyncMock(return_value=row))
    client = ScriptedClient(
        token_payload={
            "access_token": "IGQW-short",
            "user_id": IG_USER,
            "permissions": "instagram_business_basic",
        },
        me_payload={"user_id": IG_USER, "account_type": "BUSINESS"},
    )
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: client)
    db = AsyncMock()
    started = await start_oauth(db, company_id=row.company_id)
    row.oauth_connect_state = started.connect_state
    with pytest.raises(MetaOAuthError, match="meta_oauth_missing_publish"):
        await exchange_code(
            db,
            code="auth-code",
            state=f"{row.id}:{started.connect_state}",
            csrf_token=started.csrf_token,
        )


async def test_exchange_code_omitted_permissions_is_missing_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    from internal.auth import meta_oauth as mod

    row = _account()
    monkeypatch.setattr(mod.repos, "get_social_account", AsyncMock(return_value=row))
    monkeypatch.setattr(mod.repos, "get_social_account_by_id", AsyncMock(return_value=row))
    client = ScriptedClient(
        token_payload={"access_token": "IGQW-short", "user_id": IG_USER},
        me_payload={"user_id": IG_USER, "account_type": "BUSINESS"},
    )
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: client)
    db = AsyncMock()
    started = await start_oauth(db, company_id=row.company_id)
    row.oauth_connect_state = started.connect_state
    with pytest.raises(MetaOAuthError, match="meta_oauth_missing_publish"):
        await exchange_code(
            db,
            code="auth-code",
            state=f"{row.id}:{started.connect_state}",
            csrf_token=started.csrf_token,
        )


async def test_pending_connect_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    from datetime import UTC, datetime, timedelta

    from internal.auth.meta_oauth import (
        OAUTH_PENDING_TTL,
        _encrypt_connect_state,
        pending_connect_is_stale,
    )

    blob = _encrypt_connect_state("row", "csrf", f"{OAUTH_ORIGIN}/api/social/oauth/callback")
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


async def test_oauth_status_helpers_from_env_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    assert oauth_configured() is True
    assert oauth_callback_url() == f"{OAUTH_ORIGIN}/api/social/oauth/callback"

    monkeypatch.setattr(config.settings, "meta_app_secret", None)
    reset_snapshot_cache()
    assert oauth_configured() is False
    # Callback URL still derives from web_base_url alone.
    assert oauth_callback_url() == f"{OAUTH_ORIGIN}/api/social/oauth/callback"


async def test_oauth_fields_read_db_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR 0032 — creds come from the instance snapshot (DB-seeded), not env."""
    _configure(monkeypatch)
    import dataclasses

    from internal.instance.config import publish_snapshot, snapshot_from_env

    publish_snapshot(
        dataclasses.replace(
            snapshot_from_env(), meta_app_id="db-app", meta_app_secret="db-secret"
        )
    )
    monkeypatch.setattr(config.settings, "meta_app_id", None)
    monkeypatch.setattr(config.settings, "meta_app_secret", None)
    fields = _oauth_fields()
    assert fields["client_id"] == "db-app"
    assert fields["client_secret"] == "db-secret"


async def test_oauth_fields_relay_mode_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0032 — meta_oauth_mode=relay is reserved; BYO creds must not fire."""
    _configure(monkeypatch)
    import dataclasses

    from internal.instance.config import publish_snapshot, snapshot_from_env

    publish_snapshot(dataclasses.replace(snapshot_from_env(), meta_oauth_mode="relay"))
    with pytest.raises(MetaOAuthError, match="meta_oauth_mode_unavailable"):
        _oauth_fields()
    assert oauth_configured() is False
