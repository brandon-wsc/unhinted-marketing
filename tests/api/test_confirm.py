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
