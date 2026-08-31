"""Session source-trace links (ADR 0022)."""

from __future__ import annotations

import uuid

import pytest

from internal.memory import repos
from tests.api.helpers import auth_header, join_org, register_user, seed_preview_session


@pytest.mark.asyncio
async def test_session_sources_requires_auth(client) -> None:
    res = await client.get(f"/api/sessions/{uuid.uuid4()}/sources")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_session_sources_returns_cited_signals_in_order(client, db_session) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    user_id = uuid.UUID(data["user"]["id"])
    sig_a = f"sig-a-{uuid.uuid4().hex[:8]}"
    sig_b = f"sig-b-{uuid.uuid4().hex[:8]}"
    await repos.upsert_signal(
        db_session,
        signal_id=sig_a,
        source="google_trends",
        title="HK typhoon",
        url="https://example.com/typhoon",
        excerpt="weather warning",
        metrics={"rank": 1, "keyword": "typhoon"},
        region="HK",
    )
    await repos.upsert_signal(
        db_session,
        signal_id=sig_b,
        source="google_news_hk",
        title="Milk tea",
        url="https://example.com/milk-tea",
        excerpt="local drink",
        metrics={"rank": 2},
        region="HK",
    )
    await db_session.commit()

    session_id = await seed_preview_session(db_session, user_id=user_id, company_id=company_id)
    session = await repos.get_session(db_session, session_id)
    assert session is not None
    draft = await repos.get_latest_preview_draft(db_session, session_id)
    assert draft is not None
    draft.source_signal_ids = [sig_b, sig_a, "missing-id"]
    session.state = {**(session.state or {}), "source_signal_ids": [sig_b, sig_a]}
    await db_session.commit()

    res = await client.get(
        f"/api/sessions/{session_id}/sources",
        headers=auth_header(token),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source_signal_ids"] == [sig_b, sig_a, "missing-id"]
    assert [s["signal_id"] for s in body["signals"]] == [sig_b, sig_a]
    assert body["signals"][0]["title"] == "Milk tea"
    assert body["signals"][0]["url"] == "https://example.com/milk-tea"
    assert body["signals"][1]["excerpt"] == "weather warning"


@pytest.mark.asyncio
async def test_session_sources_falls_back_to_state_without_draft_ids(client, db_session) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    sig_id = f"sig-state-{uuid.uuid4().hex[:8]}"
    await repos.upsert_signal(
        db_session,
        signal_id=sig_id,
        source="tavily",
        title="From state",
        url=None,
        excerpt="chat-only citation",
        region="HK",
    )
    await db_session.commit()

    created = await client.post(
        "/api/sessions",
        headers=auth_header(token),
        json={"company_id": str(company_id)},
    )
    assert created.status_code == 201, created.text
    session_id = uuid.UUID(created.json()["id"])
    session = await repos.get_session(db_session, session_id)
    assert session is not None
    session.state = {"source_signal_ids": [sig_id]}
    await db_session.commit()

    res = await client.get(
        f"/api/sessions/{session_id}/sources",
        headers=auth_header(token),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source_signal_ids"] == [sig_id]
    assert body["signals"][0]["title"] == "From state"
    assert body["signals"][0]["url"] is None


@pytest.mark.asyncio
async def test_session_sources_forbidden_for_teammate(client, db_session) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = uuid.UUID(owner["user"]["organizations"][0]["id"])
    session_id = await seed_preview_session(
        db_session,
        user_id=uuid.UUID(owner["user"]["id"]),
        company_id=company_id,
    )
    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=company_id,
        role="member",
    )
    res = await client.get(
        f"/api/sessions/{session_id}/sources",
        headers=auth_header(member["access_token"]),
    )
    assert res.status_code == 403
