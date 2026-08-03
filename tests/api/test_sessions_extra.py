"""Extra session route coverage: messages, filters, errors, SSE snapshot."""

from __future__ import annotations

import uuid

import pytest

from internal.memory.models import SessionMessage
from tests.api.helpers import auth_header, register_user, seed_preview_session


@pytest.mark.asyncio
async def test_get_session_messages(client) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    assert created.status_code == 201
    session_id = created.json()["id"]

    res = await client.get(f"/api/sessions/{session_id}/messages", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["session"]["id"] == session_id
    assert body["messages"] == []


@pytest.mark.asyncio
async def test_session_not_found(client) -> None:
    data = await register_user(client)
    missing = uuid.uuid4()
    res = await client.get(
        f"/api/sessions/{missing}/messages",
        headers=auth_header(data["access_token"]),
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Session not found"


@pytest.mark.asyncio
async def test_create_session_company_not_found(client) -> None:
    data = await register_user(client)
    res = await client.post(
        "/api/sessions",
        headers=auth_header(data["access_token"]),
        json={"company_id": str(uuid.uuid4())},
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Company not found"


@pytest.mark.asyncio
async def test_create_session_access_denied(client) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    other = await register_user(
        client,
        email=f"oth-{uuid.uuid4().hex[:8]}@example.com",
        organization_name="Other Co",
    )
    res = await client.post(
        "/api/sessions",
        headers=auth_header(other["access_token"]),
        json={"company_id": company_id},
    )
    assert res.status_code == 403
    assert res.json()["detail"] == "Access denied"


@pytest.mark.asyncio
async def test_list_sessions_by_company_forbidden(client) -> None:
    owner = await register_user(client, email=f"own2-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    other = await register_user(
        client,
        email=f"oth2-{uuid.uuid4().hex[:8]}@example.com",
        organization_name="Other Co 2",
    )
    res = await client.get(
        "/api/sessions",
        headers=auth_header(other["access_token"]),
        params={"company_id": company_id},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_list_sessions_by_company_ok(client, db_session) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]
    # Seed a user message so list title falls back to preview text
    db_session.add(
        SessionMessage(
            session_id=uuid.UUID(session_id),
            role="user",
            content="first user preview title",
            metadata_={},
        )
    )
    await db_session.commit()

    res = await client.get("/api/sessions", headers=headers, params={"company_id": company_id})
    assert res.status_code == 200
    sessions = res.json()["sessions"]
    assert any(s["id"] == session_id for s in sessions)
    match = next(s for s in sessions if s["id"] == session_id)
    assert match["title"] == "first user preview title"


@pytest.mark.asyncio
async def test_update_session_requires_fields(client) -> None:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]
    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]

    res = await client.patch(f"/api/sessions/{session_id}", headers=headers, json={})
    assert res.status_code == 400
    assert "Provide title" in res.json()["detail"]


@pytest.mark.asyncio
async def test_update_draft_rejects_chat_mode(client) -> None:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]
    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]

    res = await client.post(
        f"/api/sessions/{session_id}/draft",
        headers=headers,
        json={"caption": "nope", "hashtags": [], "cta": ""},
    )
    assert res.status_code == 400
    assert "PREVIEW" in res.json()["detail"]


@pytest.mark.asyncio
async def test_session_events_snapshot(client, monkeypatch) -> None:
    """SSE snapshot only — subscribe is stubbed so the stream can end."""
    from collections.abc import AsyncIterator

    from internal.session import events as events_mod

    async def _empty_subscribe(_session_id: uuid.UUID) -> AsyncIterator[dict]:
        if False:  # pragma: no cover — make this an async generator
            yield {}
        return

    monkeypatch.setattr(events_mod.session_event_bus, "subscribe", _empty_subscribe)

    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]
    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]

    res = await client.get(f"/api/sessions/{session_id}/events", headers=headers)
    assert res.status_code == 200
    assert "session.snapshot" in res.text
    assert session_id in res.text


@pytest.mark.asyncio
async def test_clear_session_title(client, db_session) -> None:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    session_id = await seed_preview_session(
        db_session, user_id=user_id, company_id=company_id
    )

    named = await client.patch(
        f"/api/sessions/{session_id}",
        headers=headers,
        json={"title": "Temp"},
    )
    assert named.status_code == 200
    assert named.json()["title"] == "Temp"

    cleared = await client.patch(
        f"/api/sessions/{session_id}",
        headers=headers,
        json={"clear_title": True},
    )
    assert cleared.status_code == 200
    assert cleared.json()["title"] is None or cleared.json()["title"] == ""
