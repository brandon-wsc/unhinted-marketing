"""API tests for company product catalog."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.api.helpers import auth_header, register_user


@pytest.mark.asyncio
async def test_import_list_archive_org_products(client: AsyncClient) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])

    csv_body = "name,sku\nOat Latte,DRK-OL-12\nCold Brew Kit,DRK-CB-01\n"
    res = await client.post(
        f"/api/companies/{company_id}/products/import?scope=org",
        headers=headers,
        files={"file": ("products.csv", csv_body.encode(), "text/csv")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"] == 2
    assert body["updated"] == 0

    listed = await client.get(
        f"/api/companies/{company_id}/products?scope=org", headers=headers
    )
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 2
    assert listed.json()["can_edit"] is True
    by_sku = {i["sku"]: i for i in items}
    assert by_sku["DRK-OL-12"]["name"] == "Oat Latte"
    assert by_sku["DRK-OL-12"]["profile"]["sku"] == "DRK-OL-12"
    assert by_sku["DRK-OL-12"]["profile"]["name"] == "Oat Latte"

    # Re-import updates
    csv_body2 = "name,sku\nOat Latte Updated,DRK-OL-12\n"
    again = await client.post(
        f"/api/companies/{company_id}/products/import?scope=org",
        headers=headers,
        files={"file": ("products.csv", csv_body2.encode(), "text/csv")},
    )
    assert again.status_code == 200
    assert again.json()["updated"] == 1

    product_id = items[0]["id"]
    archived = await client.post(
        f"/api/companies/{company_id}/products/{product_id}/archive",
        headers=headers,
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    listed2 = await client.get(
        f"/api/companies/{company_id}/products?scope=org", headers=headers
    )
    assert len(listed2.json()["items"]) == 1


@pytest.mark.asyncio
async def test_mine_covered_by_company(client: AsyncClient) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])

    await client.post(
        f"/api/companies/{company_id}/products/import?scope=org",
        headers=headers,
        files={
            "file": (
                "org.csv",
                b"name,sku\nOat Latte,DRK-OL-12\n",
                "text/csv",
            )
        },
    )

    created = await client.post(
        f"/api/companies/{company_id}/products?scope=user",
        headers=headers,
        json={"name": "Oat Latte personal", "sku": "DRK-OL-12"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["covered_by_company"] is True

    personal = await client.post(
        f"/api/companies/{company_id}/products?scope=user",
        headers=headers,
        json={
            "name": "Staff pick",
            "sku": "PER-SP-01",
            "notes": "Friends & family only — oat milk default",
        },
    )
    assert personal.status_code == 201
    assert personal.json()["covered_by_company"] is False

    listed = await client.get(
        f"/api/companies/{company_id}/products?scope=user", headers=headers
    )
    assert listed.status_code == 200
    by_sku = {i["sku"]: i for i in listed.json()["items"]}
    assert by_sku["DRK-OL-12"]["covered_by_company"] is True
    assert by_sku["PER-SP-01"]["covered_by_company"] is False


@pytest.mark.asyncio
async def test_create_product_persists_notes(
    client: AsyncClient, db_session
) -> None:
    from sqlalchemy import select

    from internal.memory.models import Product

    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])

    res = await client.post(
        f"/api/companies/{company_id}/products?scope=user",
        headers=headers,
        json={
            "name": "Seasonal special",
            "sku": "SEA-01",
            "notes": "Limited autumn blend",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["profile"]["notes"] == "Limited autumn blend"
    product_id = uuid.UUID(res.json()["id"])

    row = (
        await db_session.execute(select(Product).where(Product.id == product_id))
    ).scalar_one()
    assert row.profile.get("notes") == "Limited autumn blend"
    assert "Limited autumn blend" in row.search_document


@pytest.mark.asyncio
async def test_create_product_persists_embedding(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """asyncpg vector codec rejects the stock SQLAlchemy string form."""
    from internal.memory import repos
    from internal.memory.embeddings import EMBEDDING_DIM

    dummy = [0.01] * EMBEDDING_DIM
    monkeypatch.setattr(repos, "embed_texts", lambda texts: [dummy for _ in texts])

    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])
    res = await client.post(
        f"/api/companies/{company_id}/products?scope=user",
        headers=headers,
        json={"name": "1", "sku": "1", "notes": "1"},
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_outsider_cannot_list_products(client: AsyncClient) -> None:
    owner = await register_user(client, email=f"o-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    other = await register_user(client, email=f"x-{uuid.uuid4().hex[:8]}@example.com")
    res = await client.get(
        f"/api/companies/{company_id}/products?scope=org",
        headers=auth_header(other["access_token"]),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_product_retrieve_cross_tenant_isolation(
    client: AsyncClient, db_session
) -> None:
    """K4 gate: search as company A never returns company B product ids."""
    from internal.memory.product_retrieve import search_products_for_member

    a = await register_user(
        client,
        email=f"a-{uuid.uuid4().hex[:8]}@example.com",
        organization_name="Co A",
    )
    b = await register_user(
        client,
        email=f"b-{uuid.uuid4().hex[:8]}@example.com",
        organization_name="Co B",
    )
    company_a = uuid.UUID(a["user"]["organizations"][0]["id"])
    company_b = uuid.UUID(b["user"]["organizations"][0]["id"])
    user_a = uuid.UUID(a["user"]["id"])
    user_b = uuid.UUID(b["user"]["id"])

    await client.post(
        f"/api/companies/{company_b}/products/import?scope=org",
        headers=auth_header(b["access_token"]),
        files={
            "file": (
                "b.csv",
                b"name,sku\nSecret Blend,SEC-B-99\n",
                "text/csv",
            )
        },
    )
    await client.post(
        f"/api/companies/{company_a}/products/import?scope=org",
        headers=auth_header(a["access_token"]),
        files={
            "file": (
                "a.csv",
                b"name,sku\nOat Latte,DRK-OL-12\n",
                "text/csv",
            )
        },
    )

    hits_a = await search_products_for_member(
        db_session,
        company_id=company_a,
        user_id=user_a,
        queries=["SEC-B-99", "Secret Blend"],
    )
    assert hits_a == []

    hits_b = await search_products_for_member(
        db_session,
        company_id=company_b,
        user_id=user_b,
        queries=["SEC-B-99"],
    )
    assert len(hits_b) == 1
    assert hits_b[0].product.sku == "SEC-B-99"
    assert hits_b[0].product.company_id == company_b


@pytest.mark.asyncio
async def test_patch_product_updates_fields_and_keeps_import_columns(
    client: AsyncClient, db_session
) -> None:
    from sqlalchemy import select

    from internal.memory.models import Product

    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])

    imported = await client.post(
        f"/api/companies/{company_id}/products/import?scope=user",
        headers=headers,
        files={"file": ("p.csv", b"name,sku,origin\nOat Latte,DRK-OL-12,HK\n", "text/csv")},
    )
    assert imported.status_code == 200, imported.text
    listed = await client.get(
        f"/api/companies/{company_id}/products?scope=user", headers=headers
    )
    product_id = listed.json()["items"][0]["id"]

    patched = await client.patch(
        f"/api/companies/{company_id}/products/{product_id}",
        headers=headers,
        json={"name": "Oat Latte v2", "sku": "DRK-OL-12", "notes": "oat default"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["name"] == "Oat Latte v2"
    assert body["profile"]["notes"] == "oat default"
    assert body["profile"]["origin"] == "HK"

    row = (
        await db_session.execute(select(Product).where(Product.id == uuid.UUID(product_id)))
    ).scalar_one()
    assert "oat default" in row.search_document
    assert row.profile["origin"] == "HK"

    other = await client.post(
        f"/api/companies/{company_id}/products?scope=user",
        headers=headers,
        json={"name": "Other", "sku": "OTHER-01"},
    )
    assert other.status_code == 201
    clash = await client.patch(
        f"/api/companies/{company_id}/products/{product_id}",
        headers=headers,
        json={"name": "Oat Latte v2", "sku": "OTHER-01"},
    )
    assert clash.status_code == 409
    detail = clash.json()["detail"]
    assert detail["code"] == "sku_taken"
    assert detail["existing"]["sku"] == "OTHER-01"
    assert detail["suggested_sku"] == "OTHER-01-2"


@pytest.mark.asyncio
async def test_create_duplicate_sku_conflicts_without_overwrite(client: AsyncClient) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])

    first = await client.post(
        f"/api/companies/{company_id}/products?scope=user",
        headers=headers,
        json={"name": "Oat", "sku": "DRK-01", "notes": "orig"},
    )
    assert first.status_code == 201, first.text
    product_id = first.json()["id"]

    clash = await client.post(
        f"/api/companies/{company_id}/products?scope=user",
        headers=headers,
        json={"name": "Oat v2", "sku": "DRK-01", "notes": "new"},
    )
    assert clash.status_code == 409, clash.text
    detail = clash.json()["detail"]
    assert detail["code"] == "sku_taken"
    assert detail["existing"]["id"] == product_id
    assert detail["existing"]["name"] == "Oat"
    assert detail["suggested_sku"] == "DRK-01-2"

    listed = await client.get(
        f"/api/companies/{company_id}/products?scope=user", headers=headers
    )
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Oat"
    assert items[0]["profile"]["notes"] == "orig"

    created = await client.post(
        f"/api/companies/{company_id}/products?scope=user",
        headers=headers,
        json={"name": "Oat v2", "sku": detail["suggested_sku"]},
    )
    assert created.status_code == 201, created.text
    assert created.json()["sku"] == "DRK-01-2"

    overwritten = await client.patch(
        f"/api/companies/{company_id}/products/{product_id}",
        headers=headers,
        json={"name": "Oat v2", "sku": "DRK-01", "notes": "new"},
    )
    assert overwritten.status_code == 200, overwritten.text
    assert overwritten.json()["name"] == "Oat v2"


@pytest.mark.asyncio
async def test_member_cannot_patch_org_product(client: AsyncClient, db_session) -> None:
    from tests.api.helpers import join_org

    owner = await register_user(client, email=f"o-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    member = await register_user(client, email=f"m-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    owner_headers = auth_header(owner["access_token"])
    await client.post(
        f"/api/companies/{company_id}/products/import?scope=org",
        headers=owner_headers,
        files={"file": ("p.csv", b"name,sku\nOat,ORG-01\n", "text/csv")},
    )
    listed = await client.get(
        f"/api/companies/{company_id}/products?scope=org", headers=owner_headers
    )
    product_id = listed.json()["items"][0]["id"]
    ok = await client.patch(
        f"/api/companies/{company_id}/products/{product_id}",
        headers=owner_headers,
        json={"name": "Oat v2", "sku": "ORG-01", "notes": "shop default"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["name"] == "Oat v2"
    res = await client.patch(
        f"/api/companies/{company_id}/products/{product_id}",
        headers=auth_header(member["access_token"]),
        json={"name": "Nope", "sku": "ORG-01"},
    )
    assert res.status_code == 403
