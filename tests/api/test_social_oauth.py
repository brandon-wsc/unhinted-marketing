"""Meta OAuth connect API (ADR 0022 OAuth slice) — mocked Graph; no live Meta."""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from httpx import AsyncClient

from internal import config
from tests.api.helpers import auth_header, register_user


def _base(company_id: str) -> str:
    return f"/api/companies/{company_id}/social-accounts"


CALLBACK = "/api/social/oauth/callback"


class ScriptedGraph:
    def __init__(self, token_payload: dict, me_payload: dict | None = None) -> None:
        self._token_payload = token_payload
        self._me_payload = me_payload or {}
        self.get_urls: list[str] = []

    async def __aenter__(self) -> ScriptedGraph:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        self.get_urls.append(url)
        if "/oauth/access_token" in url:
            return httpx.Response(200, json=self._token_payload)
        return httpx.Response(200, json=self._me_payload)


@pytest.mark.asyncio
async def test_oauth_start_status_callback(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from internal.auth.meta_oauth import httpx as mod_httpx

    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
    monkeypatch.setattr(config.settings, "meta_app_id", "123456")
    monkeypatch.setattr(config.settings, "meta_app_secret", "secret123")
    monkeypatch.setattr(
        config.settings,
        "meta_oauth_redirect_uri",
        "http://localhost:8000/api/social/oauth/callback",
    )
    graph = ScriptedGraph(
        token_payload={
            "access_token": "IGQW-oauth-token-999",
            "expires_in": 5_184_000,
            "token_type": "bearer",
            "granted_scopes": [
                "instagram_basic",
                "instagram_content_publish",
                "pages_show_list",
            ],
        },
        me_payload={"id": "fbid-1", "instagram_business_account": {"id": "17841400000000"}},
    )
    monkeypatch.setattr(mod_httpx, "AsyncClient", lambda *a, **k: graph)

    started = await client.post(f"{_base(company_id)}/oauth/start", headers=headers)
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["status"] == "pending"
    assert body["authorization_url"].startswith(
        "https://www.facebook.com/v22.0/dialog/oauth?"
    )
    state = parse_qs(urlsplit(body["authorization_url"]).query)["state"][0]
    csrf_cookie = started.cookies.get("meta_oauth_csrf")
    assert csrf_cookie

    pending = await client.get(f"{_base(company_id)}/oauth/status", headers=headers)
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"

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


@pytest.mark.asyncio
async def test_oauth_requires_meta_config(client: AsyncClient) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
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
    monkeypatch.setattr(config.settings, "meta_app_id", "123456")
    monkeypatch.setattr(config.settings, "meta_app_secret", "secret123")
    monkeypatch.setattr(
        config.settings,
        "meta_oauth_redirect_uri",
        "http://localhost:8000/api/social/oauth/callback",
    )

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
