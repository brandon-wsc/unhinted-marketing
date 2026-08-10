"""API tests for company voice settings."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory.models import OrganizationMember
from internal.memory.repos import get_company
from tests.api.helpers import auth_header, register_user


@pytest.mark.asyncio
async def test_get_voice_defaults_for_owner(client: AsyncClient) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])

    res = await client.get(f"/api/companies/{company_id}/voice", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["company_id"] == company_id
    assert body["roast_level"] == 1
    assert body["locale"] == "zh-HK"
    assert body["forbidden_phrases"] == []
    assert body["tone_notes"] == ""
    assert body["can_edit"] is True


@pytest.mark.asyncio
async def test_patch_voice_persists_and_round_trips(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])

    res = await client.patch(
        f"/api/companies/{company_id}/voice",
        headers=headers,
        json={
            "roast_level": 2,
            "locale": "zh-HK",
            "forbidden_phrases": ["免費保證", "史上最強", ""],
            "tone_notes": "貼地、短、有畫面",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["roast_level"] == 2
    assert body["forbidden_phrases"] == ["免費保證", "史上最強"]
    assert body["tone_notes"] == "貼地、短、有畫面"
    assert body["can_edit"] is True

    company = await get_company(db_session, uuid.UUID(company_id))
    assert company is not None
    assert company.profile["roast_level"] == 2
    assert company.profile["forbidden_phrases"] == ["免費保證", "史上最強"]

    again = await client.get(f"/api/companies/{company_id}/voice", headers=headers)
    assert again.status_code == 200
    assert again.json()["roast_level"] == 2


@pytest.mark.asyncio
async def test_voice_forbidden_for_outsider(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    other = await register_user(client, email=f"other-{uuid.uuid4().hex[:8]}@example.com")
    headers = auth_header(other["access_token"])

    res = await client.get(f"/api/companies/{company_id}/voice", headers=headers)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_member_can_read_but_not_patch(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = uuid.UUID(owner["user"]["organizations"][0]["id"])

    member_auth = await register_user(
        client, email=f"member-{uuid.uuid4().hex[:8]}@example.com"
    )
    member_id = uuid.UUID(member_auth["user"]["id"])

    existing = await db_session.scalar(
        select(OrganizationMember).where(OrganizationMember.user_id == member_id)
    )
    assert existing is not None
    await db_session.delete(existing)
    db_session.add(
        OrganizationMember(
            user_id=member_id,
            organization_id=company_id,
            role="member",
        )
    )
    await db_session.commit()

    headers = auth_header(member_auth["access_token"])
    get_res = await client.get(f"/api/companies/{company_id}/voice", headers=headers)
    assert get_res.status_code == 200, get_res.text
    assert get_res.json()["can_edit"] is False

    patch_res = await client.patch(
        f"/api/companies/{company_id}/voice",
        headers=headers,
        json={
            "roast_level": 3,
            "locale": "zh-HK",
            "forbidden_phrases": [],
            "tone_notes": "nope",
        },
    )
    assert patch_res.status_code == 403


@pytest.mark.asyncio
async def test_voice_requires_auth(client: AsyncClient) -> None:
    res = await client.get(f"/api/companies/{uuid.uuid4()}/voice")
    assert res.status_code == 401
