"""Teammates do not browse each other's sessions (slice 5)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api.helpers import auth_header, join_org, register_user


@pytest.mark.asyncio
async def test_list_sessions_does_not_include_teammate_chats(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])

    created = await client.post("/api/sessions", headers=owner_headers, json={"company_id": company_id})
    assert created.status_code == 201, created.text
    owner_session_id = created.json()["id"]

    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    member_headers = auth_header(member["access_token"])

    listed = await client.get(
        "/api/sessions",
        headers=member_headers,
        params={"company_id": company_id},
    )
    assert listed.status_code == 200, listed.text
    ids = {row["id"] for row in listed.json()["sessions"]}
    assert owner_session_id not in ids


@pytest.mark.asyncio
async def test_member_cannot_open_teammate_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])

    created = await client.post("/api/sessions", headers=owner_headers, json={"company_id": company_id})
    session_id = created.json()["id"]

    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )

    res = await client.get(
        f"/api/sessions/{session_id}/messages",
        headers=auth_header(member["access_token"]),
    )
    assert res.status_code == 403
