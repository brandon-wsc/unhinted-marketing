import uuid

import pytest

from tests.api.helpers import auth_header, register_user


@pytest.mark.asyncio
async def test_sessions_crud(client) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    created = await client.post(
        "/sessions",
        headers=headers,
        json={"company_id": company_id},
    )
    assert created.status_code == 201, created.text
    session = created.json()
    session_id = session["id"]
    assert session["company_id"] == company_id
    assert session["mode"] == "CHAT"

    listed = await client.get("/sessions", headers=headers)
    assert listed.status_code == 200
    ids = [s["id"] for s in listed.json()["sessions"]]
    assert session_id in ids

    patched = await client.patch(
        f"/sessions/{session_id}",
        headers=headers,
        json={"title": "My thread", "pinned": True},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"] == "My thread"
    assert patched.json()["pinned"] is True

    deleted = await client.delete(f"/sessions/{session_id}", headers=headers)
    assert deleted.status_code == 204

    listed_after = await client.get("/sessions", headers=headers)
    assert session_id not in [s["id"] for s in listed_after.json()["sessions"]]


@pytest.mark.asyncio
async def test_session_ownership_forbidden(client) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    created = await client.post(
        "/sessions",
        headers=auth_header(owner["access_token"]),
        json={"company_id": company_id},
    )
    assert created.status_code == 201
    session_id = created.json()["id"]

    # New client jar so cookies/tokens don't collide
    other = await register_user(
        client,
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        organization_name="Other Co",
    )
    res = await client.patch(
        f"/sessions/{session_id}",
        headers=auth_header(other["access_token"]),
        json={"title": "hijack"},
    )
    assert res.status_code == 403
    assert res.json()["detail"] == "Access denied"


@pytest.mark.asyncio
async def test_create_session_requires_auth(client) -> None:
    res = await client.post("/sessions", json={"company_id": str(uuid.uuid4())})
    assert res.status_code == 401
