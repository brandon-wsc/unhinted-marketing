import uuid

import pytest

from tests.api.helpers import auth_header, register_user


@pytest.mark.asyncio
async def test_register_login_me_refresh_logout(client) -> None:
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
async def test_register_duplicate_email(client) -> None:
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
