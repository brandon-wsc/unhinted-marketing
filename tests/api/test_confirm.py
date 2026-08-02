import uuid

import pytest

from tests.api.helpers import auth_header, register_user, seed_preview_session


@pytest.mark.asyncio
async def test_manual_draft_update(client, db_session) -> None:
    data = await register_user(client)
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    session_id = await seed_preview_session(
        db_session,
        user_id=user_id,
        company_id=company_id,
        approval_token="seed-token-aaaaaaaa",
    )

    res = await client.post(
        f"/sessions/{session_id}/draft",
        headers=auth_header(data["access_token"]),
        json={
            "caption": "Updated caption",
            "hashtags": ["hk", "trends"],
            "cta": "Learn more",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["revision"] == 2
    assert body["mode"] == "PREVIEW"
    assert body["copy"]["caption"] == "Updated caption"
    assert body["copy"]["hashtags"] == ["hk", "trends"]
    assert body["approval_token"] != "seed-token-aaaaaaaa"


@pytest.mark.asyncio
async def test_confirm_invalid_token(client, db_session) -> None:
    data = await register_user(client)
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    session_id = await seed_preview_session(
        db_session,
        user_id=user_id,
        company_id=company_id,
        approval_token="valid-token-bbbbbbbb",
    )

    res = await client.post(
        f"/sessions/{session_id}/confirm",
        headers=auth_header(data["access_token"]),
        json={
            "approval_token": "wrong-token-xxxxxxxx",
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
            "platform": "stub",
        },
    )
    assert res.status_code == 400
    assert "approval_token" in res.json()["detail"]


@pytest.mark.asyncio
async def test_confirm_idempotency(client, db_session) -> None:
    data = await register_user(client)
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    token = "confirm-token-cccccccc"
    session_id = await seed_preview_session(
        db_session,
        user_id=user_id,
        company_id=company_id,
        approval_token=token,
    )
    idem = f"idem-{uuid.uuid4().hex}"
    headers = auth_header(data["access_token"])
    payload = {
        "approval_token": token,
        "idempotency_key": idem,
        "platform": "stub",
    }

    first = await client.post(f"/sessions/{session_id}/confirm", headers=headers, json=payload)
    assert first.status_code == 200, first.text
    receipt_id = first.json()["receipt_id"]
    assert first.json()["status"] == "stubbed"

    second = await client.post(f"/sessions/{session_id}/confirm", headers=headers, json=payload)
    assert second.status_code == 200
    assert second.json()["receipt_id"] == receipt_id
    assert second.json()["idempotency_key"] == idem


@pytest.mark.asyncio
async def test_confirm_idempotency_key_not_shared_across_users(client, db_session) -> None:
    """User-private: replaying another user's idempotency_key must not leak their receipt."""
    owner = await register_user(client, email=f"own-idem-{uuid.uuid4().hex[:8]}@example.com")
    other = await register_user(
        client,
        email=f"oth-idem-{uuid.uuid4().hex[:8]}@example.com",
        organization_name="Other Idem Co",
    )
    owner_uid = uuid.UUID(owner["user"]["id"])
    owner_cid = uuid.UUID(owner["user"]["organizations"][0]["id"])
    other_uid = uuid.UUID(other["user"]["id"])
    other_cid = uuid.UUID(other["user"]["organizations"][0]["id"])

    owner_token = "owner-confirm-token-dddd"
    other_token = "other-confirm-token-eeee"
    owner_sid = await seed_preview_session(
        db_session,
        user_id=owner_uid,
        company_id=owner_cid,
        approval_token=owner_token,
    )
    other_sid = await seed_preview_session(
        db_session,
        user_id=other_uid,
        company_id=other_cid,
        approval_token=other_token,
    )

    shared_idem = f"shared-idem-{uuid.uuid4().hex}"
    first = await client.post(
        f"/sessions/{owner_sid}/confirm",
        headers=auth_header(owner["access_token"]),
        json={
            "approval_token": owner_token,
            "idempotency_key": shared_idem,
            "platform": "stub",
        },
    )
    assert first.status_code == 200, first.text

    conflict = await client.post(
        f"/sessions/{other_sid}/confirm",
        headers=auth_header(other["access_token"]),
        json={
            "approval_token": other_token,
            "idempotency_key": shared_idem,
            "platform": "stub",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Idempotency key already used"
