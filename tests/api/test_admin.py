"""Admin LLM call record APIs (ADR 0005) — platform-level gated, not tenant RBAC."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory.models import LlmCallRecord, User
from tests.api.helpers import auth_header, register_user


def _record(**overrides) -> LlmCallRecord:
    defaults = {
        "caller": "node:reviewer",
        "node": "reviewer",
        "kind": "chat_json",
        "tier": "strong",
        "model": "gpt-test",
        "status": "ok",
        "latency_ms": 120,
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "system_prompt": "sys",
        "user_prompt": "usr",
        "response_text": '{"passed": true}',
        "parse_ok": True,
        "fallback_used": False,
    }
    defaults.update(overrides)
    return LlmCallRecord(**defaults)


async def _grant_platform_level(db_session: AsyncSession, user_id: str, level: int) -> None:
    user = await db_session.get(User, uuid.UUID(user_id))
    assert user is not None
    user.platform_level = level
    await db_session.commit()


@pytest.mark.asyncio
async def test_register_defaults_to_member_level(client) -> None:
    data = await register_user(client)
    assert data["user"]["platform_level"] == 3


@pytest.mark.asyncio
async def test_llm_calls_unauthenticated(client) -> None:
    res = await client.get("/admin/llm-calls")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_llm_calls_member_forbidden(client) -> None:
    data = await register_user(client)
    res = await client.get("/admin/llm-calls", headers=auth_header(data["access_token"]))
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_llm_calls_admin_lists_and_filters(client, db_session) -> None:
    data = await register_user(client)
    await _grant_platform_level(db_session, data["user"]["id"], 6)
    db_session.add(_record())
    db_session.add(
        _record(
            caller="worker:question_generator",
            node=None,
            status="provider_error",
            fallback_used=True,
            parse_ok=None,
            error={"kind": "timeout", "error": "timed out"},
        )
    )
    await db_session.commit()
    headers = auth_header(data["access_token"])

    res = await client.get("/admin/llm-calls", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["items"]) == 2
    assert body["limit"] == 50 and body["offset"] == 0
    # Summary must not leak prompt/response bodies.
    assert "system_prompt" not in body["items"][0]

    res = await client.get("/admin/llm-calls?node=reviewer", headers=headers)
    assert [i["node"] for i in res.json()["items"]] == ["reviewer"]

    res = await client.get("/admin/llm-calls?status=provider_error", headers=headers)
    items = res.json()["items"]
    assert len(items) == 1 and items[0]["fallback_used"] is True

    res = await client.get("/admin/llm-calls?fallback_used=true", headers=headers)
    assert len(res.json()["items"]) == 1

    res = await client.get("/admin/llm-calls?limit=1&offset=1", headers=headers)
    body = res.json()
    assert len(body["items"]) == 1 and body["limit"] == 1 and body["offset"] == 1


@pytest.mark.asyncio
async def test_llm_call_detail_and_404(client, db_session) -> None:
    data = await register_user(client)
    await _grant_platform_level(db_session, data["user"]["id"], 9)
    row = _record()
    db_session.add(row)
    await db_session.commit()
    headers = auth_header(data["access_token"])

    res = await client.get(f"/admin/llm-calls/{row.id}", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["system_prompt"] == "sys"
    assert body["user_prompt"] == "usr"
    assert body["response_text"] == '{"passed": true}'
    assert body["parse_ok"] is True

    res = await client.get(f"/admin/llm-calls/{uuid.uuid4()}", headers=headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_llm_call_detail_member_forbidden(client, db_session) -> None:
    data = await register_user(client)
    row = _record()
    db_session.add(row)
    await db_session.commit()
    res = await client.get(
        f"/admin/llm-calls/{row.id}", headers=auth_header(data["access_token"])
    )
    assert res.status_code == 403
