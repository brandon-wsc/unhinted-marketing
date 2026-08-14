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
