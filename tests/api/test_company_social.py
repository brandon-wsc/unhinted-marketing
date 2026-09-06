"""Org Instagram credentials HTTP API (ADR 0022) — editor-only; never leaks tokens."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api.helpers import auth_header, join_org, register_user

SECRET_TOKEN = "IGQW-super-secret-long-lived-token"


def _base(company_id: str) -> str:
    return f"/api/companies/{company_id}/social-accounts"


def _assert_no_secret(payload: Any) -> None:
    dumped = str(payload)
    assert SECRET_TOKEN not in dumped
    assert "access_token_encrypted" not in dumped
    assert '"access_token"' not in dumped


@pytest.mark.asyncio
async def test_social_unauthenticated(client: AsyncClient) -> None:
    res = await client.get(f"/api/companies/{uuid.uuid4()}/social-accounts")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_social_member_forbidden(
    client: AsyncClient, db_session: AsyncSession
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
    res = await client.get(
        _base(company_id),
        headers=auth_header(member["access_token"]),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_social_crud_never_leaks_token(client: AsyncClient) -> None:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(data["access_token"])

    empty = await client.get(_base(company_id), headers=headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["items"] == []

    put = await client.put(
        f"{_base(company_id)}/instagram",
        headers=headers,
        json={
            "ig_user_id": "17841400000000",
            "access_token": SECRET_TOKEN,
            "expires_at": "2027-01-01T00:00:00Z",
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    _assert_no_secret(body)
    assert body["platform"] == "instagram"
    assert body["ig_user_id"] == "17841400000000"
    assert body["token_last4"] == SECRET_TOKEN[-4:]
    assert body["expires_at"] is not None

    listed = await client.get(_base(company_id), headers=headers)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    _assert_no_secret(listed.json())
    assert items[0]["id"] == body["id"]

    rotated = await client.put(
        f"{_base(company_id)}/instagram",
        headers=headers,
        json={"ig_user_id": "17841400000000", "access_token": "IGQW-rotated-token-value"},
    )
    assert rotated.status_code == 200
    assert rotated.json()["id"] == body["id"]
    assert rotated.json()["token_last4"] == "alue"
    _assert_no_secret(rotated.json())

    missing = await client.delete(
        f"{_base(company_id)}/facebook",
        headers=headers,
    )
    assert missing.status_code == 404

    gone = await client.delete(f"{_base(company_id)}/instagram", headers=headers)
    assert gone.status_code == 204
    after = await client.get(_base(company_id), headers=headers)
    assert after.json()["items"] == []
    again = await client.delete(f"{_base(company_id)}/instagram", headers=headers)
    assert again.status_code == 404
    assert again.json()["detail"] == "social_account_not_connected"
