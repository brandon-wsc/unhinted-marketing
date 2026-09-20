"""Meta platform callbacks (ADR 0033) — deauthorize + data-deletion endpoints.

Meta requires both URLs before an app can leave Development mode. These are
public routes authenticated by the signed_request HMAC, not by a user session.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac as hmac_mod
import json as json_mod
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from internal import config
from internal.auth.meta_oauth import relay_event_signature
from internal.instance.config import (
    publish_snapshot,
    reset_snapshot_cache,
    snapshot_from_env,
)
from internal.memory.repos import upsert_social_account
from tests.api.helpers import auth_header, register_user

OAUTH_ORIGIN = "https://unhinted.localhost:5173"
SECRET = "secret123"
IG_USER = "17841400000000"


def _signed_request(payload: dict, secret: str = SECRET) -> str:
    body = (
        base64.urlsafe_b64encode(json_mod.dumps(payload).encode()).decode().rstrip("=")
    )
    sig = base64.urlsafe_b64encode(
        hmac_mod.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return f"{sig}.{body}"


def _patch_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "meta_app_id", "123456")
    monkeypatch.setattr(config.settings, "meta_app_secret", SECRET)
    monkeypatch.setattr(config.settings, "web_base_url", OAUTH_ORIGIN)
    reset_snapshot_cache()


async def _seed_account(
    db_session: AsyncSession, company_id: str, ig_user_id: str = IG_USER
) -> None:
    await upsert_social_account(
        db_session,
        company_id=uuid.UUID(company_id),
        platform="instagram",
        ig_user_id=ig_user_id,
        access_token_encrypted="enc-token",
        token_last4="1234",
        expires_at=None,
        created_by=None,
    )
    await db_session.commit()


def _base(company_id: str) -> str:
    return f"/api/companies/{company_id}/social-accounts"


@pytest.mark.asyncio
async def test_deauthorize_disconnects_account(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
    _patch_meta(monkeypatch)
    await _seed_account(db_session, company_id)

    res = await client.post(
        "/api/social/meta/deauthorize",
        data={
            "signed_request": _signed_request(
                {"algorithm": "HMAC-SHA256", "user_id": IG_USER}
            )
        },
    )
    assert res.status_code == 200, res.text

    accounts = await client.get(_base(company_id), headers=headers)
    assert accounts.json()["items"] == []
    status = await client.get(f"{_base(company_id)}/oauth/status", headers=headers)
    assert status.json()["status"] == "not_connected"


@pytest.mark.asyncio
async def test_deauthorize_bad_signature_keeps_account(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
    _patch_meta(monkeypatch)
    await _seed_account(db_session, company_id)

    res = await client.post(
        "/api/social/meta/deauthorize",
        data={"signed_request": _signed_request({"user_id": IG_USER}, "wrong-secret")},
    )
    assert res.status_code == 400
    assert "meta_oauth_invalid_signed_request" in res.text

    accounts = await client.get(_base(company_id), headers=headers)
    assert len(accounts.json()["items"]) == 1


@pytest.mark.asyncio
async def test_deauthorize_unknown_user_is_noop(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await register_user(client)
    _patch_meta(monkeypatch)
    res = await client.post(
        "/api/social/meta/deauthorize",
        data={
            "signed_request": _signed_request(
                {"algorithm": "HMAC-SHA256", "user_id": "never-seen"}
            )
        },
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_data_deletion_returns_confirmation_and_status(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
    _patch_meta(monkeypatch)
    await _seed_account(db_session, company_id)

    res = await client.post(
        "/api/social/meta/data-deletion",
        data={
            "signed_request": _signed_request(
                {"algorithm": "HMAC-SHA256", "user_id": IG_USER}
            )
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["confirmation_code"]
    assert body["url"].startswith(
        f"{OAUTH_ORIGIN}/api/social/meta/data-deletion/"
    )
    assert body["url"].endswith(body["confirmation_code"])

    accounts = await client.get(_base(company_id), headers=headers)
    assert accounts.json()["items"] == []

    code = body["url"].rsplit("/", 1)[1]
    status = await client.get(f"/api/social/meta/data-deletion/{code}")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["confirmation_code"] == code


@pytest.mark.asyncio
async def test_data_deletion_status_rejects_bad_code(client: AsyncClient) -> None:
    res = await client.get("/api/social/meta/data-deletion/not-a-real-code")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_data_deletion_bad_signature(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await register_user(client)
    _patch_meta(monkeypatch)
    res = await client.post(
        "/api/social/meta/data-deletion",
        data={"signed_request": _signed_request({"user_id": IG_USER}, "wrong")},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_relay_event_rejected_in_byo_mode(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await register_user(client)
    _patch_meta(monkeypatch)
    res = await client.post(
        "/api/social/meta/relay",
        json={"kind": "deauthorize", "ig_user_id": IG_USER, "sig": "x" * 64},
    )
    assert res.status_code == 400
    assert "meta_oauth_mode_unavailable" in res.text


@pytest.mark.asyncio
async def test_relay_event_disconnects_in_relay_mode(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Relay mode (ADR 0033 §3): the verified Meta event arrives via the
    vendor relay, re-signed with this install's registry slug."""
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
    _patch_meta(monkeypatch)
    publish_snapshot(
        dataclasses.replace(
            snapshot_from_env(),
            meta_oauth_mode="relay",
            meta_oauth_relay_url="https://connect.example.com",
            meta_oauth_instance_id="inst-abc",
        )
    )
    await _seed_account(db_session, company_id)

    res = await client.post(
        "/api/social/meta/relay",
        json={
            "kind": "deauthorize",
            "ig_user_id": IG_USER,
            "sig": relay_event_signature("deauthorize", IG_USER, "inst-abc"),
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    accounts = await client.get(_base(company_id), headers=headers)
    assert accounts.json()["items"] == []

    bad = await client.post(
        "/api/social/meta/relay",
        json={
            "kind": "deauthorize",
            "ig_user_id": IG_USER,
            "sig": relay_event_signature("deauthorize", IG_USER, "inst-OTHER"),
        },
    )
    assert bad.status_code == 400
    assert "meta_oauth_invalid_signed_request" in bad.text


@pytest.mark.asyncio
async def test_relay_event_data_deletion_returns_meta_shape(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    _patch_meta(monkeypatch)
    publish_snapshot(
        dataclasses.replace(
            snapshot_from_env(),
            meta_oauth_mode="relay",
            meta_oauth_relay_url="https://connect.example.com",
            meta_oauth_instance_id="inst-abc",
        )
    )
    await _seed_account(db_session, company_id)

    res = await client.post(
        "/api/social/meta/relay",
        json={
            "kind": "data_deletion",
            "ig_user_id": IG_USER,
            "sig": relay_event_signature("data_deletion", IG_USER, "inst-abc"),
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["url"].startswith(f"{OAUTH_ORIGIN}/api/social/meta/data-deletion/")
    assert body["confirmation_code"]


@pytest.mark.asyncio
async def test_oauth_status_reports_platform_urls(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0033 — the guided card / admin need all three dashboard URLs."""
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
    _patch_meta(monkeypatch)

    res = await client.get(f"{_base(company_id)}/oauth/status", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["deauthorize_url"] == f"{OAUTH_ORIGIN}/api/social/meta/deauthorize"
    assert (
        body["data_deletion_url"] == f"{OAUTH_ORIGIN}/api/social/meta/data-deletion"
    )
