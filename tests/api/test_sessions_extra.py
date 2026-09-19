"""Extra session route coverage: messages, filters, errors, SSE snapshot."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from internal.memory.models import PreviewDraft, Session, SessionMessage
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
    assert body["recommended_image_format"] is None
    assert body["awaiting_image_ok"] is False


@pytest.mark.asyncio
async def test_get_session_messages_image_park_returns_locked_format(
    client, db_session
) -> None:
    """Reload at the image park must surface the locked format (ADR 0030)."""
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]
    row = await db_session.get(Session, uuid.UUID(session_id))
    assert row is not None
    row.state = {
        "awaiting_image_ok": True,
        "image_format": "comic_4panel",
        "brief": {"angles": ["甲"], "can_do": [], "cannot_do": [], "summary": "x"},
    }
    await db_session.commit()

    res = await client.get(f"/api/sessions/{session_id}/messages", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["awaiting_image_ok"] is True
    assert body["awaiting_angle_pick"] is False
    assert body["recommended_image_format"] == "comic_4panel"


@pytest.mark.asyncio
async def test_get_session_messages_image_park_defaults_format_single(
    client, db_session
) -> None:
    """No locked format in state → hydrate still returns the default, not null."""
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]
    row = await db_session.get(Session, uuid.UUID(session_id))
    assert row is not None
    row.state = {"awaiting_image_ok": True}
    await db_session.commit()

    res = await client.get(f"/api/sessions/{session_id}/messages", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["awaiting_image_ok"] is True
    assert body["recommended_image_format"] == "single"


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
async def test_list_sessions_search(client, db_session) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    # Session A: keyword only in a message body
    created_a = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    a_id = created_a.json()["id"]
    db_session.add(
        SessionMessage(
            session_id=uuid.UUID(a_id),
            role="user",
            content="我想推廣中秋月餅禮盒",
            metadata_={},
        )
    )
    # Session B: keyword only in the title
    created_b = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    b_id = created_b.json()["id"]
    renamed = await client.patch(
        f"/api/sessions/{b_id}", headers=headers, json={"title": "月餅 giveaway 構思"}
    )
    assert renamed.status_code == 200
    # Session C: unrelated
    created_c = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    c_id = created_c.json()["id"]
    db_session.add(
        SessionMessage(
            session_id=uuid.UUID(c_id),
            role="user",
            content="夏日沙灘帖文",
            metadata_={},
        )
    )
    await db_session.commit()

    res = await client.get(
        "/api/sessions", headers=headers, params={"company_id": company_id, "q": "月餅"}
    )
    assert res.status_code == 200, res.text
    sessions = res.json()["sessions"]
    ids = {s["id"] for s in sessions}
    assert a_id in ids
    assert b_id in ids
    assert c_id not in ids

    match_a = next(s for s in sessions if s["id"] == a_id)
    assert "月餅" in match_a["matched_snippet"]
    # Title-only match has no message snippet
    match_b = next(s for s in sessions if s["id"] == b_id)
    assert match_b["matched_snippet"] is None

    # No match → empty list
    res_none = await client.get("/api/sessions", headers=headers, params={"q": "冇呢樣嘢xyz"})
    assert res_none.status_code == 200
    assert res_none.json()["sessions"] == []

    # ILIKE wildcards in the query are escaped, not treated as patterns
    res_wild = await client.get("/api/sessions", headers=headers, params={"q": "%"})
    assert res_wild.status_code == 200
    assert res_wild.json()["sessions"] == []


@pytest.mark.asyncio
async def test_list_sessions_search_case_insensitive_and_scoped(client, db_session) -> None:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]
    db_session.add(
        SessionMessage(
            session_id=uuid.UUID(session_id),
            role="assistant",
            content="Hello IG Caption draft",
            metadata_={},
        )
    )
    await db_session.commit()

    res = await client.get("/api/sessions", headers=headers, params={"q": "hello ig"})
    assert res.status_code == 200
    assert [s["id"] for s in res.json()["sessions"]] == [session_id]

    # Another user cannot search across someone else's history
    other = await register_user(
        client,
        email=f"searcher-{uuid.uuid4().hex[:8]}@example.com",
        organization_name="Other Co",
    )
    res_other = await client.get(
        "/api/sessions", headers=auth_header(other["access_token"]), params={"q": "hello ig"}
    )
    assert res_other.status_code == 200
    assert res_other.json()["sessions"] == []


@pytest.mark.asyncio
async def test_list_sessions_search_brief_and_draft(client, db_session) -> None:
    """User-visible side-channel content (brief / draft copy) is searchable."""
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]

    # Keyword only in the brief (sessions.state JSONB)
    created_a = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    a_id = created_a.json()["id"]
    sess_a = await db_session.get(Session, uuid.UUID(a_id))
    assert sess_a is not None
    sess_a.state = {
        "brief": {
            "summary": "推廣手工曲奇禮盒",
            "can_do": ["IG 帖文"],
            "cannot_do": [],
            "angles": [],
        }
    }
    db_session.add(sess_a)

    # Keyword only in draft copy (preview_drafts JSONB)
    created_b = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    b_id = created_b.json()["id"]
    db_session.add(
        PreviewDraft(
            session_id=uuid.UUID(b_id),
            revision=1,
            copy={"caption": "手工曲奇 caption 登場", "hashtags": ["#曲奇"], "cta": "快啲買"},
            approval_token=f"tok-{uuid.uuid4().hex}",
        )
    )
    await db_session.commit()

    res = await client.get("/api/sessions", headers=headers, params={"q": "曲奇"})
    assert res.status_code == 200, res.text
    sessions = res.json()["sessions"]
    ids = {s["id"] for s in sessions}
    assert a_id in ids
    assert b_id in ids
    snip_a = next(s for s in sessions if s["id"] == a_id)["matched_snippet"]
    snip_b = next(s for s in sessions if s["id"] == b_id)["matched_snippet"]
    assert "曲奇" in snip_a
    assert "曲奇" in snip_b

    # CTA / hashtag text inside draft copy is searchable too
    res_cta = await client.get("/api/sessions", headers=headers, params={"q": "快啲買"})
    assert [s["id"] for s in res_cta.json()["sessions"]] == [b_id]


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
async def test_session_events_releases_db_while_streaming(client, engine, monkeypatch) -> None:
    """Idle SSE must not keep a QueuePool connection checked out."""
    from collections.abc import AsyncIterator

    from internal.session import events as events_mod

    hang = asyncio.Event()
    entered = asyncio.Event()
    checked_out_during_stream: dict[str, int] = {}

    async def _hang_subscribe(_session_id: uuid.UUID) -> AsyncIterator[dict]:
        checked_out_during_stream["n"] = engine.sync_engine.pool.checkedout()
        entered.set()
        await hang.wait()
        if False:  # pragma: no cover — make this an async generator
            yield {}

    monkeypatch.setattr(events_mod.session_event_bus, "subscribe", _hang_subscribe)

    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]
    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]
    idle = engine.sync_engine.pool.checkedout()

    task = asyncio.create_task(client.get(f"/api/sessions/{session_id}/events", headers=headers))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert checked_out_during_stream["n"] == idle
        me = await client.get("/api/auth/me", headers=headers)
        assert me.status_code == 200
    finally:
        hang.set()
        res = await asyncio.wait_for(task, timeout=5)
    assert res.status_code == 200
    assert "session.snapshot" in res.text


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
