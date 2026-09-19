"""API coverage for ADR 0004 stop / resume-image / parked 409 + ADR 0028 choose-angle."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from internal.session.service import SessionTurnConflict
from tests.api.helpers import auth_header, register_user


@pytest.mark.asyncio
async def test_stop_idle(client) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    assert created.status_code == 201
    session_id = created.json()["id"]

    res = await client.post(f"/api/sessions/{session_id}/stop", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "idle"


@pytest.mark.asyncio
async def test_messages_conflict_when_parked(client) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]

    with patch(
        "cmd.api.routes.sessions.run_session_turn",
        AsyncMock(
            side_effect=SessionTurnConflict(
                "parked",
                "Session is awaiting image confirmation — use resume-image or stop",
            )
        ),
    ):
        res = await client.post(
            f"/api/sessions/{session_id}/messages",
            headers=headers,
            json={"content": "ignore me"},
        )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["reason"] == "parked"


@pytest.mark.asyncio
async def test_resume_image_not_parked(client) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]

    with patch(
        "cmd.api.routes.sessions.resume_image_turn",
        AsyncMock(side_effect=SessionTurnConflict("not_parked", "not parked")),
    ):
        res = await client.post(f"/api/sessions/{session_id}/resume-image", headers=headers)
    assert res.status_code == 409
    assert res.json()["detail"]["reason"] == "not_parked"


@pytest.mark.asyncio
async def test_resume_image_happy_path(client) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]
    sid = uuid.UUID(session_id)

    fake_result = {
        "interrupted": False,
        "events": [],
        "values": {"revision": 1, "pending_confirm": False, "approval_token": None},
    }
    with patch(
        "cmd.api.routes.sessions.resume_image_turn",
        AsyncMock(return_value=fake_result),
    ):
        res = await client.post(f"/api/sessions/{session_id}/resume-image", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["session"]["id"] == str(sid)
    assert body["interrupted"] is False


@pytest.mark.asyncio
async def test_choose_angle_not_parked(client) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]

    with patch(
        "cmd.api.routes.sessions.choose_angle_turn",
        AsyncMock(side_effect=SessionTurnConflict("not_parked", "not parked")),
    ):
        res = await client.post(
            f"/api/sessions/{session_id}/choose-angle",
            headers=headers,
            json={"angle_index": 0},
        )
    assert res.status_code == 409
    assert res.json()["detail"]["reason"] == "not_parked"


@pytest.mark.asyncio
async def test_choose_angle_requires_a_pick(client) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]

    res = await client.post(
        f"/api/sessions/{session_id}/choose-angle",
        headers=headers,
        json={},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_choose_angle_index_out_of_range(client) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]

    with patch(
        "cmd.api.routes.sessions.choose_angle_turn",
        AsyncMock(side_effect=ValueError("angle_index out of range")),
    ):
        res = await client.post(
            f"/api/sessions/{session_id}/choose-angle",
            headers=headers,
            json={"angle_index": 9},
        )
    assert res.status_code == 422
    assert "out of range" in res.json()["detail"]


@pytest.mark.asyncio
async def test_choose_angle_happy_path(client) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]
    sid = uuid.UUID(session_id)

    fake_result = {
        "interrupted": True,
        "events": [
            {"type": "draft.awaiting_image_ok", "data": {"awaiting": True}},
        ],
        "values": {"revision": 0, "pending_confirm": False, "approval_token": None},
    }
    choose = AsyncMock(return_value=fake_result)
    with patch("cmd.api.routes.sessions.choose_angle_turn", choose):
        res = await client.post(
            f"/api/sessions/{session_id}/choose-angle",
            headers=headers,
            json={"angle_index": 1},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["session"]["id"] == str(sid)
    assert body["interrupted"] is True
    assert choose.await_args.kwargs["angle_index"] == 1
    assert choose.await_args.kwargs["angle_text"] is None
    assert choose.await_args.kwargs["persona"] is None


@pytest.mark.asyncio
async def test_choose_angle_forwards_persona(client) -> None:
    data = await register_user(client)
    token = data["access_token"]
    company_id = data["user"]["organizations"][0]["id"]
    headers = auth_header(token)

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    session_id = created.json()["id"]

    fake_result = {
        "interrupted": False,
        "events": [],
        "values": {"revision": 0, "pending_confirm": False, "approval_token": None},
    }
    choose = AsyncMock(return_value=fake_result)
    with patch("cmd.api.routes.sessions.choose_angle_turn", choose):
        res = await client.post(
            f"/api/sessions/{session_id}/choose-angle",
            headers=headers,
            json={"angle_index": 0, "persona": "hk_parents"},
        )
    assert res.status_code == 200, res.text
    assert choose.await_args.kwargs["persona"] == "hk_parents"


@pytest.mark.asyncio
async def test_choose_angle_rejects_other_users_session(client) -> None:
    owner = await register_user(client)
    owner_company = owner["user"]["organizations"][0]["id"]
    created = await client.post(
        "/api/sessions",
        headers=auth_header(owner["access_token"]),
        json={"company_id": owner_company},
    )
    session_id = created.json()["id"]

    other = await register_user(client)
    res = await client.post(
        f"/api/sessions/{session_id}/choose-angle",
        headers=auth_header(other["access_token"]),
        json={"angle_index": 0},
    )
    assert res.status_code in (403, 404)
