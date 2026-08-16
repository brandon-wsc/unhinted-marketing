"""API tests for org invite lifecycle (slice 2).

Written before implementation — green once invite routes + notify seam land.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory.models import Entity, OrgInvite
from tests.api.helpers import (
    auth_header,
    invite_token_from_url,
    join_org,
    register_user,
    strip_org_membership,
)


async def _create_invite(
    client: AsyncClient,
    *,
    company_id: str,
    headers: dict[str, str],
    email: str,
    role: str = "member",
) -> dict:
    res = await client.post(
        f"/api/companies/{company_id}/invites",
        headers=headers,
        json={"email": email, "role": role},
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.mark.asyncio
async def test_create_invite_returns_invite_url(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    invite_email = f"invitee-{uuid.uuid4().hex[:8]}@example.com"

    body = await _create_invite(
        client,
        company_id=company_id,
        headers=auth_header(owner["access_token"]),
        email=invite_email,
        role="admin",
    )

    assert body["email"] == invite_email
    assert body["role"] == "admin"
    assert "/invite/" in body["invite_url"]
    token = invite_token_from_url(body["invite_url"])
    assert len(token) >= 32


@pytest.mark.asyncio
async def test_preview_invite_is_public(client: AsyncClient) -> None:
    owner = await register_user(
        client,
        email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        organization_name="Harbour Co",
    )
    company_id = owner["user"]["organizations"][0]["id"]
    invite_email = f"invitee-{uuid.uuid4().hex[:8]}@example.com"
    created = await _create_invite(
        client,
        company_id=company_id,
        headers=auth_header(owner["access_token"]),
        email=invite_email,
    )
    token = invite_token_from_url(created["invite_url"])

    res = await client.get(f"/api/invites/{token}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body == {"email": invite_email, "company_name": "Harbour Co"}


@pytest.mark.asyncio
async def test_preview_unknown_token(client: AsyncClient) -> None:
    res = await client.get("/api/invites/not-a-real-token")
    assert res.status_code == 400
    assert "email" not in res.json()


@pytest.mark.asyncio
async def test_preview_expired_invite(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    created = await _create_invite(
        client,
        company_id=company_id,
        headers=auth_header(owner["access_token"]),
        email=f"expired-{uuid.uuid4().hex[:8]}@example.com",
    )
    token = invite_token_from_url(created["invite_url"])
    invite_row = await db_session.scalar(select(OrgInvite).where(OrgInvite.id == uuid.UUID(created["id"])))
    assert invite_row is not None
    invite_row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    res = await client.get(f"/api/invites/{token}")
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_preview_revoked_invite(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])
    created = await _create_invite(
        client,
        company_id=company_id,
        headers=owner_headers,
        email=f"revoked-{uuid.uuid4().hex[:8]}@example.com",
    )
    token = invite_token_from_url(created["invite_url"])
    await client.delete(f"/api/companies/{company_id}/invites/{created['id']}", headers=owner_headers)

    res = await client.get(f"/api/invites/{token}")
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_create_invite_normalizes_email(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    raw_email = f"Invitee-{uuid.uuid4().hex[:8]}@Example.COM"

    body = await _create_invite(
        client,
        company_id=company_id,
        headers=auth_header(owner["access_token"]),
        email=raw_email,
    )
    assert body["email"] == raw_email.lower()


@pytest.mark.asyncio
async def test_create_invite_rejects_invalid_email(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    headers = auth_header(owner["access_token"])

    for raw in ("d", "d@", "a@a", "not-an-email"):
        res = await client.post(
            f"/api/companies/{company_id}/invites",
            headers=headers,
            json={"email": raw, "role": "member"},
        )
        assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_create_invite_rejects_existing_member(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_email = owner["user"]["email"]

    res = await client.post(
        f"/api/companies/{company_id}/invites",
        headers=auth_header(owner["access_token"]),
        json={"email": owner_email.upper(), "role": "member"},
    )
    assert res.status_code == 409, res.text
    assert "already belongs to a member" in res.json()["detail"]


@pytest.mark.asyncio
async def test_list_pending_invites_owner_only(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])
    invite_email = f"pending-{uuid.uuid4().hex[:8]}@example.com"

    created = await _create_invite(
        client,
        company_id=company_id,
        headers=owner_headers,
        email=invite_email,
    )

    res = await client.get(f"/api/companies/{company_id}/invites", headers=owner_headers)
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == created["id"]
    assert items[0]["email"] == invite_email
    assert items[0]["accepted_at"] is None
    assert items[0]["revoked_at"] is None


@pytest.mark.asyncio
async def test_member_cannot_create_or_list_invites(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]

    member_auth = await register_user(client, email=f"member-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member_auth["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    headers = auth_header(member_auth["access_token"])

    create_res = await client.post(
        f"/api/companies/{company_id}/invites",
        headers=headers,
        json={"email": f"blocked-{uuid.uuid4().hex[:8]}@example.com", "role": "member"},
    )
    assert create_res.status_code == 403

    list_res = await client.get(f"/api/companies/{company_id}/invites", headers=headers)
    assert list_res.status_code == 403


@pytest.mark.asyncio
async def test_revoke_pending_invite(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])

    created = await _create_invite(
        client,
        company_id=company_id,
        headers=owner_headers,
        email=f"revoke-{uuid.uuid4().hex[:8]}@example.com",
    )

    del_res = await client.delete(
        f"/api/companies/{company_id}/invites/{created['id']}",
        headers=owner_headers,
    )
    assert del_res.status_code == 204, del_res.text

    list_res = await client.get(f"/api/companies/{company_id}/invites", headers=owner_headers)
    assert list_res.status_code == 200
    assert list_res.json()["items"] == []


@pytest.mark.asyncio
async def test_duplicate_pending_invite_rejected(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])
    email = f"dup-{uuid.uuid4().hex[:8]}@example.com"

    await _create_invite(client, company_id=company_id, headers=owner_headers, email=email)

    again = await client.post(
        f"/api/companies/{company_id}/invites",
        headers=owner_headers,
        json={"email": email, "role": "member"},
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_reinvite_after_revoke(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])
    email = f"reinvite-{uuid.uuid4().hex[:8]}@example.com"

    first = await _create_invite(client, company_id=company_id, headers=owner_headers, email=email)
    await client.delete(
        f"/api/companies/{company_id}/invites/{first['id']}",
        headers=owner_headers,
    )

    second = await _create_invite(client, company_id=company_id, headers=owner_headers, email=email)
    assert second["id"] != first["id"]


@pytest.mark.asyncio
async def test_cannot_invite_owner_role(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]

    res = await client.post(
        f"/api/companies/{company_id}/invites",
        headers=auth_header(owner["access_token"]),
        json={"email": f"owner-role-{uuid.uuid4().hex[:8]}@example.com", "role": "owner"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_accept_invite_joins_org(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])
    invite_email = f"accept-{uuid.uuid4().hex[:8]}@example.com"

    created = await _create_invite(
        client,
        company_id=company_id,
        headers=owner_headers,
        email=invite_email,
        role="member",
    )
    token = invite_token_from_url(created["invite_url"])

    invitee = await register_user(client, email=invite_email, password="password123")
    await strip_org_membership(db_session, uuid.UUID(invitee["user"]["id"]))

    accept_res = await client.post(
        f"/api/invites/{token}/accept",
        headers=auth_header(invitee["access_token"]),
    )
    assert accept_res.status_code == 200, accept_res.text
    body = accept_res.json()
    assert body["company_id"] == company_id
    assert body["role"] == "member"

    me = await client.get("/api/auth/me", headers=auth_header(invitee["access_token"]))
    assert me.status_code == 200
    orgs = me.json()["organizations"]
    assert len(orgs) == 1
    assert orgs[0]["id"] == company_id
    assert orgs[0]["role"] == "member"


@pytest.mark.asyncio
async def test_accept_replaces_bootstrap_solo_org(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])
    invite_email = f"busy-{uuid.uuid4().hex[:8]}@example.com"

    created = await _create_invite(
        client,
        company_id=company_id,
        headers=owner_headers,
        email=invite_email,
    )
    token = invite_token_from_url(created["invite_url"])

    invitee = await register_user(client, email=invite_email)
    bootstrap_id = uuid.UUID(invitee["user"]["organizations"][0]["id"])

    accept_res = await client.post(
        f"/api/invites/{token}/accept",
        headers=auth_header(invitee["access_token"]),
    )
    assert accept_res.status_code == 200, accept_res.text
    assert accept_res.json()["company_id"] == company_id

    me = await client.get("/api/auth/me", headers=auth_header(invitee["access_token"]))
    assert me.status_code == 200
    orgs = me.json()["organizations"]
    assert len(orgs) == 1
    assert orgs[0]["id"] == company_id

    db_session.expire_all()
    leftover = await db_session.get(Entity, bootstrap_id)
    assert leftover is None


@pytest.mark.asyncio
async def test_accept_rehomes_solo_products_to_mine(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    dest_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])
    invite_email = f"rehome-{uuid.uuid4().hex[:8]}@example.com"

    created = await _create_invite(
        client,
        company_id=dest_id,
        headers=owner_headers,
        email=invite_email,
    )
    token = invite_token_from_url(created["invite_url"])

    invitee = await register_user(client, email=invite_email)
    bootstrap_id = invitee["user"]["organizations"][0]["id"]
    invitee_headers = auth_header(invitee["access_token"])

    org_import = await client.post(
        f"/api/companies/{bootstrap_id}/products/import?scope=org",
        headers=invitee_headers,
        files={"file": ("org.csv", b"name,sku\nSolo Latte,SLT-01\nShared Sku,DUP-01\n", "text/csv")},
    )
    assert org_import.status_code == 200, org_import.text
    mine_import = await client.post(
        f"/api/companies/{bootstrap_id}/products/import?scope=user",
        headers=invitee_headers,
        files={"file": ("mine.csv", b"name,sku\nMy Cookie,CKE-01\nShared Sku Mine,DUP-01\n", "text/csv")},
    )
    assert mine_import.status_code == 200, mine_import.text

    voice = await client.patch(
        f"/api/companies/{bootstrap_id}/voice",
        headers=invitee_headers,
        json={
            "roast_level": 3,
            "locale": "zh-HK",
            "forbidden_phrases": ["舊公司口吻"],
            "tone_notes": "invitee voice",
            "exemplar_captions": [],
        },
    )
    assert voice.status_code == 200, voice.text

    accept_res = await client.post(f"/api/invites/{token}/accept", headers=invitee_headers)
    assert accept_res.status_code == 200, accept_res.text

    mine = await client.get(
        f"/api/companies/{dest_id}/products?scope=user",
        headers=invitee_headers,
    )
    assert mine.status_code == 200, mine.text
    by_sku = {item["sku"]: item for item in mine.json()["items"]}
    assert by_sku["SLT-01"]["name"] == "Solo Latte"
    assert by_sku["SLT-01"]["owner_scope"] == "user"
    assert by_sku["CKE-01"]["name"] == "My Cookie"
    assert by_sku["DUP-01"]["name"] == "Shared Sku"
    assert "Shared Sku Mine" not in {item["name"] for item in mine.json()["items"]}

    dest_voice = await client.get(f"/api/companies/{dest_id}/voice", headers=invitee_headers)
    assert dest_voice.status_code == 200
    pack = dest_voice.json()
    assert pack["roast_level"] != 3
    assert "舊公司口吻" not in pack["forbidden_phrases"]
    assert pack["tone_notes"] != "invitee voice"

    db_session.expire_all()
    leftover = await db_session.get(Entity, uuid.UUID(bootstrap_id))
    assert leftover is None


@pytest.mark.asyncio
async def test_accept_rejects_when_already_in_real_team(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])
    invite_email = f"teammate-{uuid.uuid4().hex[:8]}@example.com"

    created = await _create_invite(
        client,
        company_id=company_id,
        headers=owner_headers,
        email=invite_email,
    )
    token = invite_token_from_url(created["invite_url"])

    invitee = await register_user(client, email=invite_email)
    other = await register_user(client, email=f"other-{uuid.uuid4().hex[:8]}@example.com")
    other_company = other["user"]["organizations"][0]["id"]
    await join_org(
        db_session,
        user_id=uuid.UUID(invitee["user"]["id"]),
        company_id=uuid.UUID(other_company),
        role="member",
    )

    accept_res = await client.post(
        f"/api/invites/{token}/accept",
        headers=auth_header(invitee["access_token"]),
    )
    assert accept_res.status_code == 409


@pytest.mark.asyncio
async def test_accept_email_mismatch(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])
    invite_email = f"bound-{uuid.uuid4().hex[:8]}@example.com"

    created = await _create_invite(
        client,
        company_id=company_id,
        headers=owner_headers,
        email=invite_email,
    )
    token = invite_token_from_url(created["invite_url"])

    other = await register_user(client, email=f"other-{uuid.uuid4().hex[:8]}@example.com")
    await strip_org_membership(db_session, uuid.UUID(other["user"]["id"]))

    accept_res = await client.post(
        f"/api/invites/{token}/accept",
        headers=auth_header(other["access_token"]),
    )
    assert accept_res.status_code == 403


@pytest.mark.asyncio
async def test_accept_expired_invite(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])
    invite_email = f"expired-{uuid.uuid4().hex[:8]}@example.com"

    created = await _create_invite(
        client,
        company_id=company_id,
        headers=owner_headers,
        email=invite_email,
    )
    token = invite_token_from_url(created["invite_url"])

    invite_row = await db_session.scalar(select(OrgInvite).where(OrgInvite.id == uuid.UUID(created["id"])))
    assert invite_row is not None
    invite_row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    invitee = await register_user(client, email=invite_email)
    await strip_org_membership(db_session, uuid.UUID(invitee["user"]["id"]))

    accept_res = await client.post(
        f"/api/invites/{token}/accept",
        headers=auth_header(invitee["access_token"]),
    )
    assert accept_res.status_code == 400


@pytest.mark.asyncio
async def test_accept_revoked_invite(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])
    invite_email = f"revoked-{uuid.uuid4().hex[:8]}@example.com"

    created = await _create_invite(
        client,
        company_id=company_id,
        headers=owner_headers,
        email=invite_email,
    )
    token = invite_token_from_url(created["invite_url"])

    await client.delete(
        f"/api/companies/{company_id}/invites/{created['id']}",
        headers=owner_headers,
    )

    invitee = await register_user(client, email=invite_email)
    await strip_org_membership(db_session, uuid.UUID(invitee["user"]["id"]))

    accept_res = await client.post(
        f"/api/invites/{token}/accept",
        headers=auth_header(invitee["access_token"]),
    )
    assert accept_res.status_code == 400


@pytest.mark.asyncio
async def test_accept_single_use(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])
    invite_email = f"once-{uuid.uuid4().hex[:8]}@example.com"

    created = await _create_invite(
        client,
        company_id=company_id,
        headers=owner_headers,
        email=invite_email,
    )
    token = invite_token_from_url(created["invite_url"])

    invitee = await register_user(client, email=invite_email)
    await strip_org_membership(db_session, uuid.UUID(invitee["user"]["id"]))
    invitee_headers = auth_header(invitee["access_token"])

    first = await client.post(f"/api/invites/{token}/accept", headers=invitee_headers)
    assert first.status_code == 200, first.text

    await strip_org_membership(db_session, uuid.UUID(invitee["user"]["id"]))

    second = await client.post(f"/api/invites/{token}/accept", headers=invitee_headers)
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_outsider_cannot_list_invites(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"owner-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    outsider = await register_user(client, email=f"outsider-{uuid.uuid4().hex[:8]}@example.com")

    res = await client.get(
        f"/api/companies/{company_id}/invites",
        headers=auth_header(outsider["access_token"]),
    )
    assert res.status_code == 403
