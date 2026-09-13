"""On-prem first-run setup + invite-only register (ADR 0026)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from internal.config import settings
from tests.api.helpers import auth_header, invite_token_from_url, register_user


@pytest.fixture
def cloud_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "deployment_mode", "cloud")


def _setup_body(email: str) -> dict:
    return {
        "email": email,
        "password": "password123",
        "display_name": "First Admin",
        "organization_name": "First Co",
    }


async def _run_setup(client: AsyncClient) -> dict:
    res = await client.post("/api/setup", json=_setup_body(f"admin-{uuid.uuid4().hex[:8]}@example.com"))
    assert res.status_code == 201, res.text
    return res.json()


@pytest.mark.asyncio
async def test_setup_status_pending_on_fresh_onprem(client: AsyncClient) -> None:
    res = await client.get("/api/setup/status")
    assert res.status_code == 200
    body = res.json()
    assert body["deployment_mode"] == "onprem"
    assert body["setup_required"] is True
    assert body["web_base_url"]


@pytest.mark.asyncio
async def test_setup_creates_superadmin_and_seals(client: AsyncClient) -> None:
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    res = await client.post(
        "/api/setup",
        json={**_setup_body(email), "web_base_url": "https://mktg.example.com/"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["user"]["email"] == email
    assert body["user"]["platform_level"] == 9
    org = body["user"]["organizations"][0]
    assert org["name"] == "First Co"
    assert org["role"] == "owner"
    assert "refresh_token" in res.cookies

    status = (await client.get("/api/setup/status")).json()
    assert status["setup_required"] is False

    # The base URL landed on the instance row (trailing slash stripped).
    got = await client.get(
        "/api/instance/settings", headers=auth_header(body["access_token"])
    )
    assert got.status_code == 200
    assert got.json()["web_base_url"] == "https://mktg.example.com"
    assert got.json()["setup_completed"] is True

    again = await client.post("/api/setup", json=_setup_body(f"second-{uuid.uuid4().hex[:8]}@example.com"))
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_setup_organization_name_optional(client: AsyncClient) -> None:
    body = _setup_body(f"admin-{uuid.uuid4().hex[:8]}@example.com")
    del body["organization_name"]
    res = await client.post("/api/setup", json=body)
    assert res.status_code == 201, res.text
    org = res.json()["user"]["organizations"][0]
    assert org["name"] == "First Admin's Company"


@pytest.mark.asyncio
async def test_setup_rejected_on_cloud(client: AsyncClient, cloud_mode) -> None:
    res = await client.post("/api/setup", json=_setup_body(f"admin-{uuid.uuid4().hex[:8]}@example.com"))
    assert res.status_code == 404
    status = (await client.get("/api/setup/status")).json()
    assert status["setup_required"] is False


@pytest.mark.asyncio
async def test_onprem_register_blocked_then_invite_only(client: AsyncClient) -> None:
    invited_email = f"invitee-{uuid.uuid4().hex[:8]}@example.com"

    # Before setup, self-serve register points users at the wizard.
    res = await client.post(
        "/api/auth/register",
        json={
            "email": f"early-{uuid.uuid4().hex[:8]}@example.com",
            "password": "password123",
            "display_name": "Early",
        },
    )
    assert res.status_code == 403
    assert res.json()["detail"] == "setup_required"

    owner = await _run_setup(client)
    company_id = owner["user"]["organizations"][0]["id"]

    # After setup, register without an invite is rejected.
    res = await client.post(
        "/api/auth/register",
        json={
            "email": invited_email,
            "password": "password123",
            "display_name": "Invited",
        },
    )
    assert res.status_code == 403
    assert res.json()["detail"] == "invite_required"

    invite = await client.post(
        f"/api/companies/{company_id}/invites",
        headers=auth_header(owner["access_token"]),
        json={"email": invited_email, "role": "member"},
    )
    assert invite.status_code == 201, invite.text
    token = invite_token_from_url(invite.json()["invite_url"])

    # Email mismatch against the invite is rejected.
    res = await client.post(
        "/api/auth/register",
        json={
            "email": f"other-{uuid.uuid4().hex[:8]}@example.com",
            "password": "password123",
            "display_name": "Other",
            "invite_token": token,
        },
    )
    assert res.status_code == 403
    assert res.json()["detail"] == "invite_required"

    # Matching email + token registers.
    res = await client.post(
        "/api/auth/register",
        json={
            "email": invited_email,
            "password": "password123",
            "display_name": "Invited",
            "invite_token": token,
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["user"]["platform_level"] == 3


@pytest.mark.asyncio
async def test_cloud_register_stays_open(client: AsyncClient, cloud_mode) -> None:
    res = await client.post(
        "/api/auth/register",
        json={
            "email": f"open-{uuid.uuid4().hex[:8]}@example.com",
            "password": "password123",
            "display_name": "Open",
        },
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_instance_settings_gating(client: AsyncClient) -> None:
    owner = await _run_setup(client)
    member = await register_user(client)
    admin = await register_user(client, platform_level=6)

    # Members cannot read instance settings.
    res = await client.get("/api/instance/settings", headers=auth_header(member["access_token"]))
    assert res.status_code == 403

    # Platform admins can read but not write.
    res = await client.get("/api/instance/settings", headers=auth_header(admin["access_token"]))
    assert res.status_code == 200
    res = await client.put(
        "/api/instance/settings",
        headers=auth_header(admin["access_token"]),
        json={"web_base_url": "https://nope.example.com"},
    )
    assert res.status_code == 403

    # Superadmin edits persist and are reflected in the snapshot.
    res = await client.put(
        "/api/instance/settings",
        headers=auth_header(owner["access_token"]),
        json={"web_base_url": "https://mktg2.example.com"},
    )
    assert res.status_code == 200
    assert res.json()["web_base_url"] == "https://mktg2.example.com"


@pytest.mark.asyncio
async def test_invite_url_uses_db_base_url(client: AsyncClient) -> None:
    owner = await _run_setup(client)
    company_id = owner["user"]["organizations"][0]["id"]

    res = await client.put(
        "/api/instance/settings",
        headers=auth_header(owner["access_token"]),
        json={"web_base_url": "https://portal.example.com"},
    )
    assert res.status_code == 200

    invite = await client.post(
        f"/api/companies/{company_id}/invites",
        headers=auth_header(owner["access_token"]),
        json={"email": f"inv-{uuid.uuid4().hex[:8]}@example.com", "role": "member"},
    )
    assert invite.status_code == 201, invite.text
    assert invite.json()["invite_url"].startswith("https://portal.example.com/invite/")
