"""API tests for Mine → org product proposals (ADR 0011 / K6)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.api.helpers import auth_header, join_org, register_user


async def _mine_product(client: AsyncClient, company_id: str, headers: dict, sku: str = "PER-01") -> str:
    res = await client.post(
        f"/api/companies/{company_id}/products?scope=user",
        headers=headers,
        json={"name": "Staff pick", "sku": sku, "notes": "oat default"},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


@pytest.mark.asyncio
async def test_propose_approve_upserts_org(
    client: AsyncClient, db_session
) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    member_headers = auth_header(member["access_token"])
    owner_headers = auth_header(owner["access_token"])

    product_id = await _mine_product(client, company_id, member_headers)
    proposed = await client.post(
        f"/api/companies/{company_id}/products/{product_id}/propose",
        headers=member_headers,
    )
    assert proposed.status_code == 201, proposed.text
    body = proposed.json()
    assert body["status"] == "pending"
    assert body["sku"] == "PER-01"
    assert body["proposed_by_email"] == member["user"]["email"]
    proposal_id = body["id"]

    listed = await client.get(
        f"/api/companies/{company_id}/products?scope=user",
        headers=member_headers,
    )
    assert listed.json()["items"][0]["pending_proposal_id"] == proposal_id

    again = await client.post(
        f"/api/companies/{company_id}/products/{product_id}/propose",
        headers=member_headers,
    )
    assert again.status_code == 409

    member_list = await client.get(
        f"/api/companies/{company_id}/proposals",
        headers=member_headers,
    )
    assert member_list.status_code == 403

    queue = await client.get(
        f"/api/companies/{company_id}/proposals",
        headers=owner_headers,
    )
    assert queue.status_code == 200
    assert len(queue.json()["items"]) == 1
    assert any(f["change"] == "added" for f in queue.json()["items"][0]["fields"])

    approved = await client.post(
        f"/api/companies/{company_id}/proposals/{proposal_id}/approve",
        headers=owner_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    replay = await client.post(
        f"/api/companies/{company_id}/proposals/{proposal_id}/approve",
        headers=owner_headers,
    )
    assert replay.status_code == 200
    assert replay.json()["status"] == "approved"

    org = await client.get(
        f"/api/companies/{company_id}/products?scope=org",
        headers=owner_headers,
    )
    by_sku = {i["sku"]: i for i in org.json()["items"]}
    assert by_sku["PER-01"]["name"] == "Staff pick"
    assert by_sku["PER-01"]["profile"]["notes"] == "oat default"


@pytest.mark.asyncio
async def test_reject_leaves_org_unchanged(client: AsyncClient, db_session) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    member_headers = auth_header(member["access_token"])
    owner_headers = auth_header(owner["access_token"])

    product_id = await _mine_product(client, company_id, member_headers, sku="REJ-01")
    proposed = await client.post(
        f"/api/companies/{company_id}/products/{product_id}/propose",
        headers=member_headers,
    )
    proposal_id = proposed.json()["id"]

    rejected = await client.post(
        f"/api/companies/{company_id}/proposals/{proposal_id}/reject",
        headers=owner_headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    org = await client.get(
        f"/api/companies/{company_id}/products?scope=org",
        headers=owner_headers,
    )
    assert org.json()["items"] == []


@pytest.mark.asyncio
async def test_cannot_propose_org_or_others_mine(client: AsyncClient, db_session) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    owner_headers = auth_header(owner["access_token"])
    imported = await client.post(
        f"/api/companies/{company_id}/products/import?scope=org",
        headers=owner_headers,
        files={"file": ("p.csv", b"name,sku\nOrg Row,ORG-01\n", "text/csv")},
    )
    assert imported.status_code == 200
    org_id = (await client.get(
        f"/api/companies/{company_id}/products?scope=org", headers=owner_headers
    )).json()["items"][0]["id"]

    forbidden = await client.post(
        f"/api/companies/{company_id}/products/{org_id}/propose",
        headers=owner_headers,
    )
    assert forbidden.status_code == 403

    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    mine_id = await _mine_product(client, company_id, owner_headers, sku="OWN-01")
    steal = await client.post(
        f"/api/companies/{company_id}/products/{mine_id}/propose",
        headers=auth_header(member["access_token"]),
    )
    assert steal.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_approve_or_reject(client: AsyncClient, db_session) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    member_headers = auth_header(member["access_token"])
    product_id = await _mine_product(client, company_id, member_headers, sku="MEM-01")
    proposal_id = (
        await client.post(
            f"/api/companies/{company_id}/products/{product_id}/propose",
            headers=member_headers,
        )
    ).json()["id"]

    approved = await client.post(
        f"/api/companies/{company_id}/proposals/{proposal_id}/approve",
        headers=member_headers,
    )
    rejected = await client.post(
        f"/api/companies/{company_id}/proposals/{proposal_id}/reject",
        headers=member_headers,
    )
    assert approved.status_code == 403
    assert rejected.status_code == 403


@pytest.mark.asyncio
async def test_proposer_can_cancel_then_repropose(client: AsyncClient, db_session) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    other = await register_user(client, email=f"oth-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    await join_org(
        db_session,
        user_id=uuid.UUID(other["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    member_headers = auth_header(member["access_token"])
    owner_headers = auth_header(owner["access_token"])
    product_id = await _mine_product(client, company_id, member_headers, sku="CAN-01")
    proposal_id = (
        await client.post(
            f"/api/companies/{company_id}/products/{product_id}/propose",
            headers=member_headers,
        )
    ).json()["id"]

    stolen = await client.post(
        f"/api/companies/{company_id}/proposals/{proposal_id}/cancel",
        headers=auth_header(other["access_token"]),
    )
    assert stolen.status_code == 403

    cancelled = await client.post(
        f"/api/companies/{company_id}/proposals/{proposal_id}/cancel",
        headers=member_headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    replay = await client.post(
        f"/api/companies/{company_id}/proposals/{proposal_id}/cancel",
        headers=member_headers,
    )
    assert replay.status_code == 200
    assert replay.json()["status"] == "cancelled"

    listed = await client.get(
        f"/api/companies/{company_id}/products?scope=user",
        headers=member_headers,
    )
    assert listed.json()["items"][0]["pending_proposal_id"] is None

    queue = await client.get(
        f"/api/companies/{company_id}/proposals",
        headers=owner_headers,
    )
    assert queue.json()["items"] == []

    again = await client.post(
        f"/api/companies/{company_id}/products/{product_id}/propose",
        headers=member_headers,
    )
    assert again.status_code == 201, again.text
    assert again.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_reject_then_repropose_same_content(client: AsyncClient, db_session) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    member_headers = auth_header(member["access_token"])
    owner_headers = auth_header(owner["access_token"])
    product_id = await _mine_product(client, company_id, member_headers, sku="RETRY-01")
    first = await client.post(
        f"/api/companies/{company_id}/products/{product_id}/propose",
        headers=member_headers,
    )
    proposal_id = first.json()["id"]
    rejected = await client.post(
        f"/api/companies/{company_id}/proposals/{proposal_id}/reject",
        headers=owner_headers,
    )
    assert rejected.status_code == 200

    again = await client.post(
        f"/api/companies/{company_id}/products/{product_id}/propose",
        headers=member_headers,
    )
    assert again.status_code == 201, again.text
    assert again.json()["id"] != proposal_id
    assert again.json()["status"] == "pending"
    assert again.json()["sku"] == "RETRY-01"

    replay_reject = await client.post(
        f"/api/companies/{company_id}/proposals/{proposal_id}/approve",
        headers=owner_headers,
    )
    assert replay_reject.status_code == 409


@pytest.mark.asyncio
async def test_propose_snapshot_ignores_later_mine_edits(
    client: AsyncClient, db_session
) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    member_headers = auth_header(member["access_token"])
    owner_headers = auth_header(owner["access_token"])
    product_id = await _mine_product(client, company_id, member_headers, sku="SNAP-01")
    proposed = await client.post(
        f"/api/companies/{company_id}/products/{product_id}/propose",
        headers=member_headers,
    )
    proposal_id = proposed.json()["id"]
    assert proposed.json()["profile"]["notes"] == "oat default"

    patched = await client.patch(
        f"/api/companies/{company_id}/products/{product_id}",
        headers=member_headers,
        json={"name": "Staff pick v2", "sku": "SNAP-01", "notes": "changed after propose"},
    )
    assert patched.status_code == 200, patched.text

    queue = await client.get(
        f"/api/companies/{company_id}/proposals",
        headers=owner_headers,
    )
    item = next(i for i in queue.json()["items"] if i["id"] == proposal_id)
    assert item["name"] == "Staff pick"
    assert item["profile"]["notes"] == "oat default"


@pytest.mark.asyncio
async def test_approve_replaces_existing_org_sku(client: AsyncClient, db_session) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    owner_headers = auth_header(owner["access_token"])
    member_headers = auth_header(member["access_token"])
    imported = await client.post(
        f"/api/companies/{company_id}/products/import?scope=org",
        headers=owner_headers,
        files={"file": ("p.csv", b"name,sku,notes\nOld Org,REP-01,shop default\n", "text/csv")},
    )
    assert imported.status_code == 200, imported.text

    created = await client.post(
        f"/api/companies/{company_id}/products?scope=user",
        headers=member_headers,
        json={"name": "New Mine", "sku": "REP-01", "notes": "member rewrite"},
    )
    assert created.status_code == 201, created.text
    product_id = created.json()["id"]
    proposed = await client.post(
        f"/api/companies/{company_id}/products/{product_id}/propose",
        headers=member_headers,
    )
    assert proposed.status_code == 201, proposed.text
    fields = {f["key"]: f for f in proposed.json()["fields"]}
    assert fields["name"]["change"] == "changed"
    assert fields["name"]["current"] == "Old Org"
    assert fields["name"]["proposed"] == "New Mine"

    approved = await client.post(
        f"/api/companies/{company_id}/proposals/{proposed.json()['id']}/approve",
        headers=owner_headers,
    )
    assert approved.status_code == 200, approved.text
    org = await client.get(
        f"/api/companies/{company_id}/products?scope=org",
        headers=owner_headers,
    )
    by_sku = {i["sku"]: i for i in org.json()["items"]}
    assert by_sku["REP-01"]["name"] == "New Mine"
    assert by_sku["REP-01"]["profile"]["notes"] == "member rewrite"
