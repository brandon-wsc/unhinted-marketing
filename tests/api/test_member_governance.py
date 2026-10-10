"""API tests for member usage limits + publish approval (ADR 0041)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory.models import (
    LlmCallRecord,
    OrganizationMember,
    Session,
    ToolReceipt,
)
from internal.tools.publish import STUB_STATUS, PublishOutcome
from tests.api.helpers import (
    auth_header,
    join_org,
    register_user,
    seed_preview_session,
)


def _llm_record(user_id: uuid.UUID, company_id: uuid.UUID, **overrides) -> LlmCallRecord:
    defaults = {
        "caller": "node:reviewer",
        "node": "reviewer",
        "kind": "chat_json",
        "tier": "strong",
        "model": "gpt-test",
        "status": "ok",
        "latency_ms": 10,
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "system_prompt": "sys",
        "user_prompt": "usr",
        "response_text": "{}",
        "parse_ok": True,
        "fallback_used": False,
        "user_id": user_id,
        "company_id": company_id,
        "key_source": "env",
    }
    defaults.update(overrides)
    return LlmCallRecord(**defaults)


async def _join(
    db_session: AsyncSession,
    user_id: str,
    company_id: uuid.UUID,
    *,
    role: str = "member",
    monthly_token_limit: int | None = None,
) -> OrganizationMember:
    membership = await join_org(
        db_session,
        user_id=uuid.UUID(user_id),
        company_id=company_id,
        role=role,
    )
    membership.monthly_token_limit = monthly_token_limit
    await db_session.commit()
    return membership


def _stub_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _turn(*args, **kwargs):
        return {"values": {}, "interrupted": False, "events": []}

    monkeypatch.setattr("cmd.api.routes.sessions.run_session_turn", _turn)


async def _org_pair(client: AsyncClient, db_session: AsyncSession):
    """Owner + member in the same company. Returns (owner, member, company_id)."""
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = uuid.UUID(owner["user"]["organizations"][0]["id"])
    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    await _join(db_session, member["user"]["id"], company_id)
    return owner, member, company_id


# ---------------------------------------------------------------------------
# Usage limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_over_limit_gets_403_structured(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_turn(monkeypatch)
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = uuid.UUID(owner["user"]["organizations"][0]["id"])
    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    member_id = uuid.UUID(member["user"]["id"])
    await _join(db_session, member["user"]["id"], company_id, monthly_token_limit=100)

    db_session.add(_llm_record(member_id, company_id, total_tokens=80))
    db_session.add(_llm_record(member_id, company_id, total_tokens=40))
    await db_session.commit()

    session_id = await seed_preview_session(
        db_session, user_id=member_id, company_id=company_id, with_media=False
    )
    res = await client.post(
        f"/api/sessions/{session_id}/messages",
        headers=auth_header(member["access_token"]),
        json={"content": "draft a post"},
    )
    assert res.status_code == 403, res.text
    detail = res.json()["detail"]
    assert detail["reason"] == "usage_limit_exceeded"
    assert detail["limit"] == 100
    assert detail["used"] == 120
    assert detail["period_end"]


@pytest.mark.asyncio
async def test_org_key_usage_does_not_count(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BYOK spend (key_source='org') never counts against the member cap."""
    _stub_turn(monkeypatch)
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = uuid.UUID(owner["user"]["organizations"][0]["id"])
    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    member_id = uuid.UUID(member["user"]["id"])
    await _join(db_session, member["user"]["id"], company_id, monthly_token_limit=100)

    db_session.add(_llm_record(member_id, company_id, total_tokens=10_000, key_source="org"))
    # Another user's env spend in the same org must not count either.
    db_session.add(_llm_record(uuid.UUID(owner["user"]["id"]), company_id, total_tokens=10_000))
    await db_session.commit()

    session_id = await seed_preview_session(
        db_session, user_id=member_id, company_id=company_id, with_media=False
    )
    res = await client.post(
        f"/api/sessions/{session_id}/messages",
        headers=auth_header(member["access_token"]),
        json={"content": "draft a post"},
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_owner_and_admin_bypass_member_limit(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_turn(monkeypatch)
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = uuid.UUID(owner["user"]["organizations"][0]["id"])
    owner_id = uuid.UUID(owner["user"]["id"])
    admin = await register_user(client, email=f"adm-{uuid.uuid4().hex[:8]}@example.com")
    admin_id = uuid.UUID(admin["user"]["id"])
    await _join(db_session, admin["user"]["id"], company_id, role="admin")

    # Seed spend that would blow any limit; roles owner/admin skip the check.
    db_session.add(_llm_record(owner_id, company_id, total_tokens=9_999))
    db_session.add(_llm_record(admin_id, company_id, total_tokens=9_999))
    await db_session.commit()

    for auth, uid in ((owner, owner_id), (admin, admin_id)):
        session_id = await seed_preview_session(
            db_session,
            user_id=uid,
            company_id=company_id,
            approval_token=f"bypass-token-{uuid.uuid4().hex[:12]}",
            with_media=False,
        )
        res = await client.post(
            f"/api/sessions/{session_id}/messages",
            headers=auth_header(auth["access_token"]),
            json={"content": "draft a post"},
        )
        assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_member_null_limit_is_unlimited(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_turn(monkeypatch)
    _owner, member, company_id = await _org_pair(client, db_session)
    member_id = uuid.UUID(member["user"]["id"])
    db_session.add(_llm_record(member_id, company_id, total_tokens=9_999_999))
    await db_session.commit()

    session_id = await seed_preview_session(
        db_session, user_id=member_id, company_id=company_id, with_media=False
    )
    res = await client.post(
        f"/api/sessions/{session_id}/messages",
        headers=auth_header(member["access_token"]),
        json={"content": "draft a post"},
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_member_usage_meter(client: AsyncClient, db_session: AsyncSession) -> None:
    owner, member, company_id = await _org_pair(client, db_session)
    member_id = uuid.UUID(member["user"]["id"])
    await client.patch(
        f"/api/companies/{company_id}/members/{member_id}",
        headers=auth_header(owner["access_token"]),
        json={"monthly_token_limit": 500},
    )
    db_session.add(_llm_record(member_id, company_id, total_tokens=200))
    db_session.add(_llm_record(member_id, company_id, total_tokens=5_000, key_source="org"))
    await db_session.commit()

    res = await client.get(
        f"/api/companies/{company_id}/usage",
        headers=auth_header(member["access_token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["monthly_token_limit"] == 500
    assert body["used_tokens"] == 200
    assert body["remaining_tokens"] == 300
    assert body["period_start"] and body["period_end"]

    # Unlimited member → null remaining.
    owner_res = await client.get(
        f"/api/companies/{company_id}/usage",
        headers=auth_header(owner["access_token"]),
    )
    assert owner_res.status_code == 200
    assert owner_res.json()["monthly_token_limit"] is None
    assert owner_res.json()["remaining_tokens"] is None


@pytest.mark.asyncio
async def test_owner_patches_member_limit(client: AsyncClient, db_session: AsyncSession) -> None:
    owner, member, company_id = await _org_pair(client, db_session)
    member_id = member["user"]["id"]

    res = await client.patch(
        f"/api/companies/{company_id}/members/{member_id}",
        headers=auth_header(owner["access_token"]),
        json={"monthly_token_limit": 1234},
    )
    assert res.status_code == 200, res.text
    assert res.json()["monthly_token_limit"] == 1234

    cleared = await client.patch(
        f"/api/companies/{company_id}/members/{member_id}",
        headers=auth_header(owner["access_token"]),
        json={"monthly_token_limit": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["monthly_token_limit"] is None

    denied = await client.patch(
        f"/api/companies/{company_id}/members/{member_id}",
        headers=auth_header(member["access_token"]),
        json={"monthly_token_limit": 1},
    )
    assert denied.status_code == 403


# ---------------------------------------------------------------------------
# Publish approval
# ---------------------------------------------------------------------------


async def _set_policy(
    client: AsyncClient, owner: dict, company_id: uuid.UUID, enabled: bool
) -> None:
    res = await client.patch(
        f"/api/companies/{company_id}/governance",
        headers=auth_header(owner["access_token"]),
        json={"member_publish_requires_approval": enabled},
    )
    assert res.status_code == 200, res.text
    assert res.json()["member_publish_requires_approval"] is enabled


def _confirm_payload(token: str) -> dict:
    return {
        "approval_token": token,
        "idempotency_key": f"idem-{uuid.uuid4().hex}",
        "platform": "stub",
    }


@pytest.mark.asyncio
async def test_policy_off_member_confirms_directly(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backwards compat: no policy → member Confirm publishes as today."""
    calls: list[dict] = []

    async def _spy(db, req, *, company_id):
        calls.append({"platform": req.platform})
        return PublishOutcome(status=STUB_STATUS, platform="stub")

    monkeypatch.setattr("internal.tools.publish.publish_social_post", _spy)

    _owner, member, company_id = await _org_pair(client, db_session)
    token = "direct-token-aaaa"
    session_id = await seed_preview_session(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=company_id,
        approval_token=token,
    )
    res = await client.post(
        f"/api/sessions/{session_id}/confirm",
        headers=auth_header(member["access_token"]),
        json=_confirm_payload(token),
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "stubbed"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_policy_on_member_confirm_parks_without_adapter(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(*args, **kwargs):
        raise AssertionError("publish_social_post must not run while parked")

    monkeypatch.setattr("internal.tools.publish.publish_social_post", _boom)

    owner, member, company_id = await _org_pair(client, db_session)
    await _set_policy(client, owner, company_id, True)

    token = "park-token-bbbb"
    session_id = await seed_preview_session(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=company_id,
        approval_token=token,
    )
    res = await client.post(
        f"/api/sessions/{session_id}/confirm",
        headers=auth_header(member["access_token"]),
        json=_confirm_payload(token),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "pending_approval"
    assert body["tool_name"] == "publish_social_post"

    # Session stays active — nothing published yet.
    listed = await client.get("/api/sessions", headers=auth_header(member["access_token"]))
    row = next(s for s in listed.json()["sessions"] if s["id"] == str(session_id))
    assert row["status"] == "active"

    # Replay with the same idempotency key returns the parked receipt.
    replay = await client.post(
        f"/api/sessions/{session_id}/confirm",
        headers=auth_header(member["access_token"]),
        json={
            "approval_token": token,
            "idempotency_key": body["idempotency_key"],
            "platform": "stub",
        },
    )
    assert replay.status_code == 200
    assert replay.json()["receipt_id"] == body["receipt_id"]
    assert replay.json()["status"] == "pending_approval"

    # Queue is self-contained: copy, media, platform, revision, requester.
    queue = await client.get(
        f"/api/companies/{company_id}/publish-approvals",
        headers=auth_header(owner["access_token"]),
    )
    assert queue.status_code == 200, queue.text
    items = queue.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["id"] == body["receipt_id"]
    assert item["status"] == "pending_approval"
    assert item["draft_copy"]["caption"] == "seed"
    assert item["platform"] == "stub"
    assert item["revision"] == 1
    assert item["requested_by_email"] == member["user"]["email"]
    assert item["user_id"] == member["user"]["id"]


@pytest.mark.asyncio
async def test_approve_executes_publish_exactly_once(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    async def _spy(db, req, *, company_id):
        calls.append(
            {
                "approval_token": req.approval_token,
                "idempotency_key": req.idempotency_key,
            }
        )
        return PublishOutcome(status=STUB_STATUS, platform="stub")

    monkeypatch.setattr("internal.tools.publish.publish_social_post", _spy)

    owner, member, company_id = await _org_pair(client, db_session)
    await _set_policy(client, owner, company_id, True)

    token = "approve-token-cccc"
    member_id = uuid.UUID(member["user"]["id"])
    session_id = await seed_preview_session(
        db_session, user_id=member_id, company_id=company_id, approval_token=token
    )
    payload = _confirm_payload(token)
    parked = await client.post(
        f"/api/sessions/{session_id}/confirm",
        headers=auth_header(member["access_token"]),
        json=payload,
    )
    receipt_id = parked.json()["receipt_id"]

    approved = await client.post(
        f"/api/companies/{company_id}/publish-approvals/{receipt_id}/approve",
        headers=auth_header(owner["access_token"]),
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "stubbed"
    assert body["user_id"] == str(member_id)
    assert body["reviewed_by_email"] == owner["user"]["email"]

    # Same adapter call, original idempotency key, parked draft's token.
    assert len(calls) == 1
    assert calls[0]["approval_token"] == token
    assert calls[0]["idempotency_key"] == payload["idempotency_key"]

    # Receipt user stays the requesting member.
    receipt = await db_session.get(ToolReceipt, uuid.UUID(receipt_id))
    assert receipt is not None
    assert receipt.user_id == member_id

    # Repeat approve is idempotent — no second adapter call.
    again = await client.post(
        f"/api/companies/{company_id}/publish-approvals/{receipt_id}/approve",
        headers=auth_header(owner["access_token"]),
    )
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "stubbed"
    assert len(calls) == 1

    # Session marked confirmed after successful publish.
    session = await db_session.get(Session, session_id)
    assert session is not None
    assert session.status == "confirmed"


@pytest.mark.asyncio
async def test_reject_clears_pending_and_member_can_repark(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner, member, company_id = await _org_pair(client, db_session)
    await _set_policy(client, owner, company_id, True)

    token = "reject-token-dddd"
    session_id = await seed_preview_session(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=company_id,
        approval_token=token,
    )
    parked = await client.post(
        f"/api/sessions/{session_id}/confirm",
        headers=auth_header(member["access_token"]),
        json=_confirm_payload(token),
    )
    receipt_id = parked.json()["receipt_id"]

    rejected = await client.post(
        f"/api/companies/{company_id}/publish-approvals/{receipt_id}/reject",
        headers=auth_header(owner["access_token"]),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["reviewed_by_email"] == owner["user"]["email"]

    # Queue empties.
    queue = await client.get(
        f"/api/companies/{company_id}/publish-approvals",
        headers=auth_header(owner["access_token"]),
    )
    assert queue.json()["items"] == []

    # Member edits + confirms again → parks a new request.
    parked2 = await client.post(
        f"/api/sessions/{session_id}/confirm",
        headers=auth_header(member["access_token"]),
        json=_confirm_payload(token),
    )
    assert parked2.status_code == 200, parked2.text
    assert parked2.json()["status"] == "pending_approval"
    assert parked2.json()["receipt_id"] != receipt_id

    queue2 = await client.get(
        f"/api/companies/{company_id}/publish-approvals",
        headers=auth_header(owner["access_token"]),
    )
    assert len(queue2.json()["items"]) == 1


@pytest.mark.asyncio
async def test_cross_org_approval_forbidden(client: AsyncClient, db_session: AsyncSession) -> None:
    owner, member, company_id = await _org_pair(client, db_session)
    await _set_policy(client, owner, company_id, True)

    token = "cross-org-token-eeee"
    session_id = await seed_preview_session(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=company_id,
        approval_token=token,
    )
    parked = await client.post(
        f"/api/sessions/{session_id}/confirm",
        headers=auth_header(member["access_token"]),
        json=_confirm_payload(token),
    )
    receipt_id = parked.json()["receipt_id"]

    outsider = await register_user(
        client,
        email=f"out-{uuid.uuid4().hex[:8]}@example.com",
        organization_name="Outsider Co",
    )
    out_headers = auth_header(outsider["access_token"])

    listed = await client.get(f"/api/companies/{company_id}/publish-approvals", headers=out_headers)
    assert listed.status_code == 403
    approved = await client.post(
        f"/api/companies/{company_id}/publish-approvals/{receipt_id}/approve",
        headers=out_headers,
    )
    assert approved.status_code == 403
    rejected = await client.post(
        f"/api/companies/{company_id}/publish-approvals/{receipt_id}/reject",
        headers=out_headers,
    )
    assert rejected.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_use_approval_queue(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _owner, member, company_id = await _org_pair(client, db_session)
    member_headers = auth_header(member["access_token"])

    listed = await client.get(
        f"/api/companies/{company_id}/publish-approvals", headers=member_headers
    )
    assert listed.status_code == 403
    patch = await client.patch(
        f"/api/companies/{company_id}/governance",
        headers=member_headers,
        json={"member_publish_requires_approval": True},
    )
    assert patch.status_code == 403


@pytest.mark.asyncio
async def test_governance_defaults_off(client: AsyncClient, db_session: AsyncSession) -> None:
    owner, member, company_id = await _org_pair(client, db_session)
    res = await client.get(
        f"/api/companies/{company_id}/governance",
        headers=auth_header(member["access_token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["member_publish_requires_approval"] is False
    assert body["can_edit"] is False

    owner_res = await client.get(
        f"/api/companies/{company_id}/governance",
        headers=auth_header(owner["access_token"]),
    )
    assert owner_res.json()["can_edit"] is True
