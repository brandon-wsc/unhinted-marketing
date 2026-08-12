"""API tests for company membership management (ADR 0010 slice 1)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api.helpers import auth_header, join_org, register_user


@pytest.mark.asyncio
async def test_list_members_returns_org_members(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])

    member_auth = await register_user(client, email=f"member-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member_auth["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )

    res = await client.get(f"/api/companies/{company_id}/members", headers=owner_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["company_id"] == company_id
    roles = {item["user_id"]: item["role"] for item in body["items"]}
    assert roles[owner["user"]["id"]] == "owner"
    assert roles[member_auth["user"]["id"]] == "member"


@pytest.mark.asyncio
async def test_member_can_list_members(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]

    member_auth = await register_user(client, email=f"member-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member_auth["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )

    res = await client.get(
        f"/api/companies/{company_id}/members",
        headers=auth_header(member_auth["access_token"]),
    )
    assert res.status_code == 200, res.text
    assert len(res.json()["items"]) == 2


@pytest.mark.asyncio
async def test_patch_company_rename_owner_only(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])

    res = await client.patch(
        f"/api/companies/{company_id}",
        headers=owner_headers,
        json={"name": "Renamed Co"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "Renamed Co"
    assert body["slug"]  # slug unchanged on rename

    member_auth = await register_user(client, email=f"member-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member_auth["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    denied = await client.patch(
        f"/api/companies/{company_id}",
        headers=auth_header(member_auth["access_token"]),
        json={"name": "Nope"},
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_owner_changes_member_role(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])

    member_auth = await register_user(client, email=f"member-{uuid.uuid4().hex[:8]}@example.com")
    member_id = member_auth["user"]["id"]
    await join_org(
        db_session,
        user_id=uuid.UUID(member_id),
        company_id=uuid.UUID(company_id),
        role="member",
    )

    res = await client.patch(
        f"/api/companies/{company_id}/members/{member_id}",
        headers=owner_headers,
        json={"role": "admin"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_cannot_change_owner_role(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_id = owner["user"]["id"]
    headers = auth_header(owner["access_token"])

    res = await client.patch(
        f"/api/companies/{company_id}/members/{owner_id}",
        headers=headers,
        json={"role": "admin"},
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_member_can_leave_org(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]

    member_auth = await register_user(client, email=f"member-{uuid.uuid4().hex[:8]}@example.com")
    member_id = member_auth["user"]["id"]
    await join_org(
        db_session,
        user_id=uuid.UUID(member_id),
        company_id=uuid.UUID(company_id),
        role="member",
    )

    res = await client.delete(
        f"/api/companies/{company_id}/members/{member_id}",
        headers=auth_header(member_auth["access_token"]),
    )
    assert res.status_code == 204, res.text

    list_res = await client.get(
        f"/api/companies/{company_id}/members",
        headers=auth_header(owner["access_token"]),
    )
    assert list_res.status_code == 200
    user_ids = {item["user_id"] for item in list_res.json()["items"]}
    assert member_id not in user_ids


@pytest.mark.asyncio
async def test_owner_cannot_leave_org(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_id = owner["user"]["id"]

    res = await client.delete(
        f"/api/companies/{company_id}/members/{owner_id}",
        headers=auth_header(owner["access_token"]),
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_owner_removes_member(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])

    member_auth = await register_user(client, email=f"member-{uuid.uuid4().hex[:8]}@example.com")
    member_id = member_auth["user"]["id"]
    await join_org(
        db_session,
        user_id=uuid.UUID(member_id),
        company_id=uuid.UUID(company_id),
        role="member",
    )

    res = await client.delete(
        f"/api/companies/{company_id}/members/{member_id}",
        headers=owner_headers,
    )
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_cannot_remove_owner(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_id = owner["user"]["id"]

    admin_auth = await register_user(client, email=f"admin-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(admin_auth["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="admin",
    )

    res = await client.delete(
        f"/api/companies/{company_id}/members/{owner_id}",
        headers=auth_header(admin_auth["access_token"]),
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_members_forbidden_for_outsider(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    outsider = await register_user(client, email=f"other-{uuid.uuid4().hex[:8]}@example.com")

    res = await client.get(
        f"/api/companies/{company_id}/members",
        headers=auth_header(outsider["access_token"]),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_change_roles(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]

    member_auth = await register_user(client, email=f"member-{uuid.uuid4().hex[:8]}@example.com")
    other_auth = await register_user(client, email=f"other-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member_auth["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    await join_org(
        db_session,
        user_id=uuid.UUID(other_auth["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )

    res = await client.patch(
        f"/api/companies/{company_id}/members/{other_auth['user']['id']}",
        headers=auth_header(member_auth["access_token"]),
        json={"role": "admin"},
    )
    assert res.status_code == 403
