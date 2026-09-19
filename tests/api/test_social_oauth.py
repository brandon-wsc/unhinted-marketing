"""Meta OAuth connect API (ADR 0022 OAuth slice) — mocked Graph; no live Meta."""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from internal import config
from internal.auth.meta_oauth import META_OAUTH_SCOPES
from internal.instance.config import reset_snapshot_cache
from tests.api.helpers import auth_header, join_org, register_user

OAUTH_ORIGIN = "https://unhinted.localhost:5173"


def _base(company_id: str) -> str:
    return f"/api/companies/{company_id}/social-accounts"


CALLBACK = "/api/social/oauth/callback"


class ScriptedGraph:
    def __init__(
        self,
        token_payload: dict,
        me_payload: dict | None = None,
        long_lived_payload: dict | None = None,
    ) -> None:
        self._token_payload = token_payload
        self._me_payload = me_payload or {}
        self._long_lived_payload = long_lived_payload or {
            "access_token": "IGQW-oauth-token-999",
            "token_type": "bearer",
            "expires_in": 5_184_000,
        }
        self.get_urls: list[str] = []
        self.post_urls: list[str] = []

    async def __aenter__(self) -> ScriptedGraph:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, data: dict | None = None) -> httpx.Response:
        self.post_urls.append(url)
        if "api.instagram.com/oauth/access_token" in url:
            return httpx.Response(200, json=self._token_payload)
        return httpx.Response(404, json={})

    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        self.get_urls.append(url)
        if url.startswith("https://graph.instagram.com/access_token"):
            return httpx.Response(200, json=self._long_lived_payload)
        if url.rstrip("/").endswith("/me"):
            return httpx.Response(200, json=self._me_payload)
        return httpx.Response(200, json={})


def _patch_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "meta_app_id", "123456")
    monkeypatch.setattr(config.settings, "meta_app_secret", "secret123")
    monkeypatch.setattr(config.settings, "web_base_url", OAUTH_ORIGIN)
    reset_snapshot_cache()


def _ok_token() -> dict:
    return {
        "access_token": "IGQW-short",
        "user_id": "17841400000000",
        "permissions": META_OAUTH_SCOPES,
    }


async def _start_oauth(
    client: AsyncClient, headers: dict[str, str], company_id: str
) -> tuple[str, str]:
    started = await client.post(f"{_base(company_id)}/oauth/start", headers=headers)
    assert started.status_code == 201, started.text
    state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
    csrf = started.cookies.get("meta_oauth_csrf")
    assert csrf
    return state, csrf


async def _hit_callback(client: AsyncClient, *, state: str, csrf: str) -> httpx.Response:
    client.cookies.set("meta_oauth_csrf", csrf, path="/api/social")
    return await client.get(
        CALLBACK,
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )


@pytest.mark.asyncio
async def test_oauth_start_status_callback(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from internal.auth.meta_oauth import httpx as mod_httpx

    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
    _patch_meta(monkeypatch)
    graph = ScriptedGraph(
        token_payload=_ok_token(),
        me_payload={"user_id": "17841400000000", "account_type": "BUSINESS"},
    )
    monkeypatch.setattr(mod_httpx, "AsyncClient", lambda *a, **k: graph)

    started = await client.post(f"{_base(company_id)}/oauth/start", headers=headers)
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["status"] == "pending"
    assert body["authorization_url"].startswith(
        "https://www.instagram.com/oauth/authorize?"
    )
    start_query = parse_qs(urlsplit(body["authorization_url"]).query)
    assert start_query["scope"][0] == META_OAUTH_SCOPES
    assert start_query["redirect_uri"][0] == f"{OAUTH_ORIGIN}/api/social/oauth/callback"
    assert "extras" not in start_query
    assert "code_challenge" not in start_query
    state = start_query["state"][0]
    csrf_cookie = started.cookies.get("meta_oauth_csrf")
    assert csrf_cookie

    pending = await client.get(f"{_base(company_id)}/oauth/status", headers=headers)
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"

    listed_pending = await client.get(f"{_base(company_id)}", headers=headers)
    assert listed_pending.status_code == 200
    assert listed_pending.json()["items"] == []

    client.cookies.set("meta_oauth_csrf", csrf_cookie, path="/api/social")
    callback = await client.get(
        CALLBACK,
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code in (302, 307)
    location = callback.headers["location"]
    assert "oauth=done" in location
    assert "status=ok" in location
    assert "/settings" in location
    assert "tab=instagram" in location

    connected = await client.get(f"{_base(company_id)}/oauth/status", headers=headers)
    assert connected.status_code == 200
    assert connected.json()["status"] == "connected"

    accounts = await client.get(f"{_base(company_id)}", headers=headers)
    assert accounts.status_code == 200
    items = accounts.json()["items"]
    assert len(items) == 1
    assert items[0]["ig_user_id"] == "17841400000000"
    assert items[0]["token_last4"] == "-999"
    assert "access_token" not in str(accounts.json())

    graph.get_urls.clear()
    # 第二次 start 應該重新產生 pending state
    restarted = await client.post(f"{_base(company_id)}/oauth/start", headers=headers)
    assert restarted.status_code == 201
    pending2 = await client.get(f"{_base(company_id)}/oauth/status", headers=headers)
    assert pending2.json()["status"] == "pending"
    listed_rotate = await client.get(f"{_base(company_id)}", headers=headers)
    assert len(listed_rotate.json()["items"]) == 1
    assert listed_rotate.json()["items"][0]["ig_user_id"] == "17841400000000"


@pytest.mark.asyncio
async def test_oauth_callback_not_professional(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from internal.auth.meta_oauth import httpx as mod_httpx

    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
    _patch_meta(monkeypatch)
    graph = ScriptedGraph(
        token_payload=_ok_token(),
        me_payload={"id": "personal-1", "account_type": "PERSONAL"},
    )
    monkeypatch.setattr(mod_httpx, "AsyncClient", lambda *a, **k: graph)
    state, csrf = await _start_oauth(client, headers, company_id)
    callback = await _hit_callback(client, state=state, csrf=csrf)
    assert callback.status_code in (302, 307)
    location = callback.headers["location"]
    assert "oauth=done" in location
    assert "status=meta_oauth_not_professional" in location
    assert "/settings" in location
    after = await client.get(f"{_base(company_id)}/oauth/status", headers=headers)
    assert after.json()["status"] == "not_connected"


@pytest.mark.asyncio
async def test_oauth_callback_missing_publish(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from internal.auth.meta_oauth import httpx as mod_httpx

    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
    _patch_meta(monkeypatch)
    graph = ScriptedGraph(
        token_payload={
            "access_token": "IGQW-short",
            "user_id": "17841400000000",
            "permissions": "instagram_business_basic",
        },
        me_payload={"user_id": "17841400000000", "account_type": "BUSINESS"},
    )
    monkeypatch.setattr(mod_httpx, "AsyncClient", lambda *a, **k: graph)
    state, csrf = await _start_oauth(client, headers, company_id)
    callback = await _hit_callback(client, state=state, csrf=csrf)
    assert callback.status_code in (302, 307)
    location = callback.headers["location"]
    assert "oauth=done" in location
    assert "status=meta_oauth_missing_publish" in location
    after = await client.get(f"{_base(company_id)}/oauth/status", headers=headers)
    assert after.json()["status"] == "not_connected"


@pytest.mark.asyncio
async def test_oauth_requires_meta_config(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
    monkeypatch.setattr(config.settings, "meta_app_id", None)
    monkeypatch.setattr(config.settings, "meta_app_secret", None)
    res = await client.post(f"{_base(company_id)}/oauth/start", headers=headers)
    assert res.status_code == 400
    assert "meta_oauth_not_configured" in res.text


@pytest.mark.asyncio
async def test_oauth_denied_clears_state(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
    _patch_meta(monkeypatch)

    started = await client.post(f"{_base(company_id)}/oauth/start", headers=headers)
    assert started.status_code == 201
    state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]

    callback = await client.get(
        CALLBACK,
        params={"error": "access_denied", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code in (302, 307)
    assert "status=access_denied" in callback.headers["location"]

    pending = await client.get(f"{_base(company_id)}/oauth/status", headers=headers)
    assert pending.json()["status"] == "not_connected"
    listed = await client.get(f"{_base(company_id)}", headers=headers)
    assert listed.json()["items"] == []


@pytest.mark.asyncio
async def test_oauth_cancel_clears_pending(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
    _patch_meta(monkeypatch)

    started = await client.post(f"{_base(company_id)}/oauth/start", headers=headers)
    assert started.status_code == 201
    pending = await client.get(f"{_base(company_id)}/oauth/status", headers=headers)
    assert pending.json()["status"] == "pending"

    cancelled = await client.post(f"{_base(company_id)}/oauth/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "not_connected"
    after = await client.get(f"{_base(company_id)}/oauth/status", headers=headers)
    assert after.json()["status"] == "not_connected"


@pytest.mark.asyncio
async def test_oauth_status_expires_stale_pending(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
    _patch_meta(monkeypatch)
    started = await client.post(f"{_base(company_id)}/oauth/start", headers=headers)
    assert started.status_code == 201
    monkeypatch.setattr(
        "cmd.api.routes.social.pending_connect_is_stale", lambda *_a, **_k: True
    )
    expired = await client.get(f"{_base(company_id)}/oauth/status", headers=headers)
    assert expired.status_code == 200
    assert expired.json()["status"] == "not_connected"


@pytest.mark.asyncio
async def test_oauth_unauthenticated(client: AsyncClient) -> None:
    company_id = uuid.uuid4()
    status = await client.get(f"{_base(str(company_id))}/oauth/status")
    assert status.status_code == 401
    started = await client.post(f"{_base(str(company_id))}/oauth/start")
    assert started.status_code == 401
    cancelled = await client.post(f"{_base(str(company_id))}/oauth/cancel")
    assert cancelled.status_code == 401


@pytest.mark.asyncio
async def test_oauth_member_forbidden(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    headers = auth_header(member["access_token"])
    status = await client.get(f"{_base(company_id)}/oauth/status", headers=headers)
    assert status.status_code == 403
    started = await client.post(f"{_base(company_id)}/oauth/start", headers=headers)
    assert started.status_code == 403
    cancelled = await client.post(f"{_base(company_id)}/oauth/cancel", headers=headers)
    assert cancelled.status_code == 403
