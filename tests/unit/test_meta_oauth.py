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
    parse_relay_state,
    parse_state,
    redeem_relay_ticket,
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
    """ADR 0032 §3 — relay mode without a relay URL/instance_id is unconfigured."""
    _configure(monkeypatch)
    import dataclasses

    from internal.instance.config import publish_snapshot, snapshot_from_env

    publish_snapshot(dataclasses.replace(snapshot_from_env(), meta_oauth_mode="relay"))
    with pytest.raises(MetaOAuthError, match="meta_oauth_not_configured"):
        _oauth_fields()
    assert oauth_configured() is False


def _relay_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Publish a relay-mode instance snapshot."""
    import dataclasses

    from internal.instance.config import publish_snapshot, snapshot_from_env

    _configure(monkeypatch)
    publish_snapshot(
        dataclasses.replace(
            snapshot_from_env(),
            meta_oauth_mode="relay",
            meta_oauth_relay_url="https://connect.example.com",
            meta_oauth_instance_id="inst-abc",
        )
    )


async def test_relay_mode_callback_and_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Relay mode derives the fixed vendor callback and needs no local creds."""
    _relay_snapshot(monkeypatch)
    assert oauth_callback_url() == "https://connect.example.com/meta/callback"
    assert oauth_configured() is True
    fields = _oauth_fields()
    assert fields["redirect_uri"] == "https://connect.example.com/meta/callback"


async def test_start_oauth_relay_prefixes_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Relay start sends the browser to /authorize with an instance-prefixed state."""
    _relay_snapshot(monkeypatch)
    company_id = uuid.uuid4()
    db = AsyncMock()
    row = _account()
    from internal.auth import meta_oauth as mod

    async def fake_get(*a, **k):
        return row

    monkeypatch.setattr(mod.repos, "get_social_account", fake_get)

    started = await start_oauth(db, company_id=company_id)
    assert started.authorization_url.startswith("https://connect.example.com/authorize?")
    from urllib.parse import parse_qs, urlsplit

    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    assert state.startswith("inst-abc:")
    parsed = parse_relay_state(state)
    assert parsed is not None
    assert parsed[0] == str(row.id)


async def test_relay_redeem_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: valid pending state + ticket redeem upserts the account."""
    _relay_snapshot(monkeypatch)
    from internal.auth import meta_oauth as mod
    from internal.auth.meta_oauth import _encrypt_connect_state

    row = _account()
    row.oauth_connect_state = _encrypt_connect_state(
        str(row.id), "csrf-tok", "https://connect.example.com/meta/callback"
    )

    async def fake_get_by_id(*a, **k):
        return row

    upserted: list[dict] = []

    async def fake_upsert(db, **kwargs):
        upserted.append(kwargs)
        return row

    monkeypatch.setattr(mod.repos, "get_social_account_by_id", fake_get_by_id)
    monkeypatch.setattr(mod.repos, "upsert_social_account", fake_upsert)

    class TicketClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            import httpx

            assert url == "https://connect.example.com/ticket/tok-1"
            return httpx.Response(
                200,
                json={
                    "instance_id": "inst-abc",
                    "ig_user_id": IG_USER,
                    "access_token": "IGQW-relay-long",
                    "expires_at": "2026-11-19T00:00:00+00:00",
                    "missing_scopes": [],
                },
            )

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda **k: TicketClient())

    state = f"inst-abc:{row.id}:{row.oauth_connect_state}"
    result = await redeem_relay_ticket(
        db=AsyncMock(), ticket="tok-1", state=state, csrf_token="csrf-tok"
    )
    assert result.ig_user_id == IG_USER
    assert upserted and upserted[0]["ig_user_id"] == IG_USER
    assert row.oauth_connect_state is None


async def test_relay_redeem_rejects_foreign_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ticket payload bound to another install must not persist here."""
    _relay_snapshot(monkeypatch)
    from internal.auth import meta_oauth as mod
    from internal.auth.meta_oauth import _encrypt_connect_state

    row = _account()
    row.oauth_connect_state = _encrypt_connect_state(
        str(row.id), "csrf-tok", "https://connect.example.com/meta/callback"
    )

    async def fake_get_by_id(*a, **k):
        return row

    monkeypatch.setattr(mod.repos, "get_social_account_by_id", fake_get_by_id)

    class TicketClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            import httpx

            return httpx.Response(
                200,
                json={
                    "instance_id": "inst-OTHER",
                    "ig_user_id": IG_USER,
                    "access_token": "tok",
                    "expires_at": None,
                    "missing_scopes": [],
                },
            )

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda **k: TicketClient())

    state = f"inst-abc:{row.id}:{row.oauth_connect_state}"
    with pytest.raises(MetaOAuthError, match="meta_oauth_invalid_state"):
        await redeem_relay_ticket(
            db=AsyncMock(), ticket="tok-1", state=state, csrf_token="csrf-tok"
        )


async def test_relay_redeem_expired_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    _relay_snapshot(monkeypatch)
    from internal.auth import meta_oauth as mod
    from internal.auth.meta_oauth import _encrypt_connect_state

    row = _account()
    row.oauth_connect_state = _encrypt_connect_state(
        str(row.id), "csrf-tok", "https://connect.example.com/meta/callback"
    )

    async def fake_get_by_id(*a, **k):
        return row

    monkeypatch.setattr(mod.repos, "get_social_account_by_id", fake_get_by_id)

    class TicketClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            import httpx

            return httpx.Response(404, text="unknown or expired ticket")

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda **k: TicketClient())

    state = f"inst-abc:{row.id}:{row.oauth_connect_state}"
    with pytest.raises(MetaOAuthError, match="meta_oauth_relay_ticket_expired"):
        await redeem_relay_ticket(
            db=AsyncMock(), ticket="tok-1", state=state, csrf_token="csrf-tok"
        )


async def test_relay_redeem_wrong_instance_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """State prefixed for a different registry slug never reaches redemption."""
    _relay_snapshot(monkeypatch)
    row = _account()
    state = f"inst-OTHER:{row.id}:blob"
    with pytest.raises(MetaOAuthError, match="meta_oauth_invalid_state"):
        await redeem_relay_ticket(
            db=AsyncMock(), ticket="tok-1", state=state, csrf_token="x"
        )


async def test_exchange_code_blocked_in_relay_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In relay mode Meta never calls this instance — the BYO callback path
    must refuse rather than attempt an exchange with empty creds."""
    _relay_snapshot(monkeypatch)
    with pytest.raises(MetaOAuthError, match="meta_oauth_mode_unavailable"):
        await exchange_code(
            db=AsyncMock(), code="c", state="a:b", csrf_token=None
        )


# --- Meta platform callbacks (ADR 0033) ---

import base64
import hashlib
import hmac as hmac_mod
import json as json_mod

from internal.auth.meta_oauth import (
    meta_platform_callback_urls,
    parse_signed_request,
    process_data_deletion,
    process_deauthorize,
    process_relay_platform_event,
    relay_event_signature,
    verify_data_deletion_code,
)

APP_SECRET = "secret123"


def _signed_request(payload: dict, secret: str = APP_SECRET) -> str:
    body = (
        base64.urlsafe_b64encode(json_mod.dumps(payload).encode()).decode().rstrip("=")
    )
    sig = base64.urlsafe_b64encode(
        hmac_mod.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return f"{sig}.{body}"


async def test_parse_signed_request_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    raw = _signed_request(
        {"algorithm": "HMAC-SHA256", "user_id": IG_USER, "issued_at": 1}
    )
    payload = parse_signed_request(raw, APP_SECRET)
    assert payload is not None
    assert payload["user_id"] == IG_USER


async def test_parse_signed_request_rejects_tamper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    assert parse_signed_request(
        _signed_request({"user_id": IG_USER}), "other-secret"
    ) is None
    body = base64.urlsafe_b64encode(
        json_mod.dumps({"algorithm": "HMAC-SHA256", "user_id": "999"}).encode()
    ).decode().rstrip("=")
    # valid sig for a different payload must not verify
    raw = _signed_request({"algorithm": "HMAC-SHA256", "user_id": IG_USER})
    sig = raw.split(".", 1)[0]
    assert parse_signed_request(f"{sig}.{body}", APP_SECRET) is None
    assert parse_signed_request("not-a-request", APP_SECRET) is None
    assert parse_signed_request("", APP_SECRET) is None
    assert parse_signed_request(raw, "") is None
    # payload that is not a dict
    body_list = base64.urlsafe_b64encode(b"[1,2]").decode().rstrip("=")
    sig_list = base64.urlsafe_b64encode(
        hmac_mod.new(APP_SECRET.encode(), body_list.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    assert parse_signed_request(f"{sig_list}.{body_list}", APP_SECRET) is None


async def test_meta_platform_callback_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    urls = meta_platform_callback_urls()
    assert urls["deauthorize_url"] == f"{OAUTH_ORIGIN}/api/social/meta/deauthorize"
    assert urls["data_deletion_url"] == f"{OAUTH_ORIGIN}/api/social/meta/data-deletion"

    _relay_snapshot(monkeypatch)
    urls = meta_platform_callback_urls()
    assert urls["deauthorize_url"] == "https://connect.example.com/meta/deauthorize"
    assert urls["data_deletion_url"] == "https://connect.example.com/meta/data-deletion"


async def test_process_deauthorize_disconnects(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    from internal.auth import meta_oauth as mod

    deleted: list[str] = []

    async def fake_delete(db, ig_user_id):
        deleted.append(ig_user_id)
        return 1

    monkeypatch.setattr(
        mod.repos, "delete_social_accounts_by_ig_user_id", fake_delete
    )
    raw = _signed_request(
        {"algorithm": "HMAC-SHA256", "user_id": IG_USER}
    )
    ig_user_id = await process_deauthorize(AsyncMock(), signed_request=raw)
    assert ig_user_id == IG_USER
    assert deleted == [IG_USER]


async def test_process_deauthorize_bad_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    with pytest.raises(MetaOAuthError, match="meta_oauth_invalid_signed_request"):
        await process_deauthorize(
            AsyncMock(), signed_request=_signed_request({"user_id": IG_USER}, "nope")
        )


async def test_process_deauthorize_blocked_in_relay_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relay mode: Meta calls the vendor app — the instance must refuse the
    raw signed_request path and rely on the relay forward instead."""
    _relay_snapshot(monkeypatch)
    with pytest.raises(MetaOAuthError, match="meta_oauth_mode_unavailable"):
        await process_deauthorize(AsyncMock(), signed_request="a.b")


async def test_process_data_deletion_returns_status_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    from internal.auth import meta_oauth as mod

    monkeypatch.setattr(
        mod.repos,
        "delete_social_accounts_by_ig_user_id",
        AsyncMock(return_value=1),
    )
    raw = _signed_request({"algorithm": "HMAC-SHA256", "user_id": IG_USER})
    code, url = await process_data_deletion(AsyncMock(), signed_request=raw)
    assert url.startswith(f"{OAUTH_ORIGIN}/api/social/meta/data-deletion/")
    assert url.endswith(code)
    assert verify_data_deletion_code(code) == IG_USER
    assert verify_data_deletion_code(code + "x") is None
    assert verify_data_deletion_code("bogus") is None


async def test_relay_platform_event_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _relay_snapshot(monkeypatch)
    from internal.auth import meta_oauth as mod

    deleted: list[str] = []

    async def fake_delete(db, ig_user_id):
        deleted.append(ig_user_id)
        return 1

    monkeypatch.setattr(
        mod.repos, "delete_social_accounts_by_ig_user_id", fake_delete
    )
    sig = relay_event_signature("deauthorize", IG_USER, "inst-abc")
    result = await process_relay_platform_event(
        AsyncMock(), kind="deauthorize", ig_user_id=IG_USER, sig=sig
    )
    assert result == {"ok": True}
    assert deleted == [IG_USER]

    sig = relay_event_signature("data_deletion", IG_USER, "inst-abc")
    result = await process_relay_platform_event(
        AsyncMock(), kind="data_deletion", ig_user_id=IG_USER, sig=sig
    )
    assert result["url"].startswith(f"{OAUTH_ORIGIN}/api/social/meta/data-deletion/")
    assert result["confirmation_code"]


async def test_relay_platform_event_rejects_bad_sig_and_byo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _relay_snapshot(monkeypatch)
    with pytest.raises(MetaOAuthError, match="meta_oauth_invalid_signed_request"):
        await process_relay_platform_event(
            AsyncMock(), kind="deauthorize", ig_user_id=IG_USER, sig="bad"
        )
    sig_other = relay_event_signature("deauthorize", IG_USER, "inst-OTHER")
    with pytest.raises(MetaOAuthError, match="meta_oauth_invalid_signed_request"):
        await process_relay_platform_event(
            AsyncMock(), kind="deauthorize", ig_user_id=IG_USER, sig=sig_other
        )

    _configure(monkeypatch)
    with pytest.raises(MetaOAuthError, match="meta_oauth_mode_unavailable"):
        await process_relay_platform_event(
            AsyncMock(),
            kind="deauthorize",
            ig_user_id=IG_USER,
            sig=relay_event_signature("deauthorize", IG_USER, "inst-abc"),
        )
