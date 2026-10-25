import uuid

import pytest

from internal.config import settings
from tests.api.helpers import auth_header, register_user


@pytest.fixture
def cloud_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Open registration stays available on cloud (ADR 0026)."""
    monkeypatch.setattr(settings, "deployment_mode", "cloud")


@pytest.mark.asyncio
async def test_register_login_me_refresh_logout(client, cloud_mode) -> None:
    email = f"auth-{uuid.uuid4().hex[:8]}@example.com"
    password = "password123"

    reg = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": password,
            "display_name": "Auth User",
            "organization_name": "Auth Co",
        },
    )
    assert reg.status_code == 201, reg.text
    body = reg.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == email
    assert len(body["user"]["organizations"]) == 1
    assert "refresh_token" in reg.cookies

    access = body["access_token"]
    me = await client.get("/api/auth/me", headers=auth_header(access))
    assert me.status_code == 200
    assert me.json()["email"] == email

    login = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    assert login.json()["user"]["email"] == email

    refresh = await client.post("/api/auth/refresh")
    assert refresh.status_code == 200
    new_access = refresh.json()["access_token"]
    assert new_access

    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert logout.json()["message"] == "Logged out"

    # Refresh cookie cleared — subsequent refresh should fail
    again = await client.post("/api/auth/refresh")
    assert again.status_code == 401


@pytest.mark.asyncio
async def test_register_duplicate_email(client, cloud_mode) -> None:
    data = await register_user(client)
    email = data["user"]["email"]
    res = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": "Other",
        },
    )
    assert res.status_code == 409
    assert res.json()["detail"] == "Email already registered"


@pytest.mark.asyncio
async def test_login_bad_password(client) -> None:
    data = await register_user(client)
    res = await client.post(
        "/api/auth/login",
        json={"email": data["user"]["email"], "password": "wrong-password"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid email or password"


@pytest.mark.asyncio
async def test_me_missing_bearer(client) -> None:
    res = await client.get("/api/auth/me")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_patch_me_updates_display_name(client) -> None:
    data = await register_user(client, display_name="Old Name")
    access = data["access_token"]

    res = await client.patch(
        "/api/auth/me",
        headers=auth_header(access),
        json={"display_name": "  New Name  "},
    )
    assert res.status_code == 200, res.text
    assert res.json()["display_name"] == "New Name"
    assert res.json()["email"] == data["user"]["email"]

    me = await client.get("/api/auth/me", headers=auth_header(access))
    assert me.status_code == 200
    assert me.json()["display_name"] == "New Name"


@pytest.mark.asyncio
async def test_patch_me_rejects_blank_name(client) -> None:
    data = await register_user(client)
    res = await client.patch(
        "/api/auth/me",
        headers=auth_header(data["access_token"]),
        json={"display_name": "   "},
    )
    assert res.status_code == 422
    assert res.json()["detail"] == "Display name is required"


@pytest.mark.asyncio
async def test_patch_me_requires_auth(client) -> None:
    res = await client.patch("/api/auth/me", json={"display_name": "Nope"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_verify_password_accepts_current(client) -> None:
    data = await register_user(client)
    res = await client.post(
        "/api/auth/me/verify-password",
        headers=auth_header(data["access_token"]),
        json={"password": "password123"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"message": "ok"}


@pytest.mark.asyncio
async def test_verify_password_rejects_wrong(client) -> None:
    data = await register_user(client)
    res = await client.post(
        "/api/auth/me/verify-password",
        headers=auth_header(data["access_token"]),
        json={"password": "wrong-password"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Current password is incorrect"


@pytest.mark.asyncio
async def test_verify_password_requires_auth(client) -> None:
    res = await client.post("/api/auth/me/verify-password", json={"password": "password123"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_change_password_success_and_relogin(client) -> None:
    data = await register_user(client)
    email = data["user"]["email"]
    access = data["access_token"]

    res = await client.post(
        "/api/auth/me/password",
        headers=auth_header(access),
        json={"current_password": "password123", "new_password": "newpassword456"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"message": "Password changed"}

    # Old password no longer logs in; new one does.
    old_login = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert old_login.status_code == 401
    new_login = await client.post(
        "/api/auth/login", json={"email": email, "password": "newpassword456"}
    )
    assert new_login.status_code == 200

    # Verify now accepts only the new password.
    old_check = await client.post(
        "/api/auth/me/verify-password",
        headers=auth_header(access),
        json={"password": "password123"},
    )
    assert old_check.status_code == 401
    new_check = await client.post(
        "/api/auth/me/verify-password",
        headers=auth_header(access),
        json={"password": "newpassword456"},
    )
    assert new_check.status_code == 200


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_current(client) -> None:
    data = await register_user(client)
    res = await client.post(
        "/api/auth/me/password",
        headers=auth_header(data["access_token"]),
        json={"current_password": "wrong-password", "new_password": "newpassword456"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Current password is incorrect"


@pytest.mark.asyncio
async def test_change_password_rejects_same_as_current(client) -> None:
    data = await register_user(client)
    res = await client.post(
        "/api/auth/me/password",
        headers=auth_header(data["access_token"]),
        json={"current_password": "password123", "new_password": "password123"},
    )
    assert res.status_code == 422
    assert res.json()["detail"] == "New password must be different from the current password"


@pytest.mark.asyncio
async def test_change_password_rejects_short_new(client) -> None:
    data = await register_user(client)
    res = await client.post(
        "/api/auth/me/password",
        headers=auth_header(data["access_token"]),
        json={"current_password": "password123", "new_password": "short"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_change_password_requires_auth(client) -> None:
    res = await client.post(
        "/api/auth/me/password",
        json={"current_password": "password123", "new_password": "newpassword456"},
    )
    assert res.status_code == 401
