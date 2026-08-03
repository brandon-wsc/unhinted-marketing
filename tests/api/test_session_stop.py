"""API coverage for ADR 0004 stop / resume-image / parked 409."""

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
