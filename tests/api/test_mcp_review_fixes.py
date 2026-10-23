"""Regression tests for the ADR 0051 branch review (B1–B3).

The 14 BDD scenarios cover the happy contract; these pin down what the
review found missing:

- revoke → re-consent must never resurrect old tokens (new grant id, old
  refresh tokens stay revoked);
- refresh rotation binds ``client_id`` and kills the family on reuse;
- the ADR 0041 member cap is enforced before the session commits and at
  every automatic gate turn — no orphan sessions;
- ``get_post_draft`` maps pending/running/failed/awaiting_reply/ready
  instead of defaulting to ``ready``;
- ``revise_post_draft`` refuses while a turn runs;
- OAuth errors are RFC 6749-shaped with ``Cache-Control: no-store``;
- ``last_used_at`` actually lands in the DB.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from internal.mcp import grants as grant_repo
from internal.mcp import oauth, tools
from internal.mcp.auth import McpContext
from internal.mcp.errors import ToolRefusal
from internal.mcp.tokens import McpAccessClaims, create_mcp_access_token
from internal.memory import repos
from internal.memory.database import open_session
from internal.memory.models import LlmCallRecord, OAuthRefreshToken, Session, SessionMessage
from internal.session import service
from internal.session.graph import set_session_graph
from internal.session.guards import MemberTokenLimitExceeded
from internal.session.state import MODE_PREVIEW
from schemas.mcp import (
    RevisePostDraftArgs,
    SessionToolArgs,
    StartPostDraftArgs,
)
from tests.api.helpers import join_org, register_user
from tests.api.mcp_helpers import (
    STUB_RECOMMENDED_ANGLE,
    TEST_CLIENT_ID,
    TEST_CLIENT_NAME,
    ParkingSessionGraph,
    rpc_body,
    rpc_headers,
)

SCOPES = ["knowledge:read", "drafts:write", "images:generate"]


async def _grant(user_id: uuid.UUID, company_id: uuid.UUID, scopes=None):
    async with open_session() as db:
        grant = await grant_repo.issue_grant(
            db,
            user_id=user_id,
            company_id=company_id,
            client_id=TEST_CLIENT_ID,
            client_name=TEST_CLIENT_NAME,
            scopes=scopes or SCOPES,
        )
        await db.commit()
        return grant


async def _ctx(client, *, scopes=None, email: str | None = None):
    """register_user + grant → a real McpContext (bypasses token verification)."""
    body = await register_user(client, email=email)
    user_id = uuid.UUID(body["user"]["id"])
    company_id = uuid.UUID(body["user"]["organizations"][0]["id"])
    grant = await _grant(user_id, company_id, scopes)
    claims = McpAccessClaims(
        user_id=user_id,
        company_id=company_id,
        grant_id=grant.id,
        scopes=list(grant.scopes or []),
    )
    return McpContext(claims=claims, grant=grant, user=None), body


# --- B1: revoke → re-consent ---------------------------------------------------


async def test_revoking_a_grant_revokes_its_refresh_tokens(client) -> None:
    ctx, _body = await _ctx(client)
    async with open_session() as db:
        refresh = await oauth._mint_refresh(db, ctx.grant)
        await db.commit()

        assert await grant_repo.revoke_grant(db, user_id=ctx.claims.user_id, grant_id=ctx.grant.id)
        await db.commit()

        row = await db.scalar(
            select(OAuthRefreshToken).where(
                OAuthRefreshToken.token_hash == oauth.hash_refresh_token(refresh)
            )
        )
        assert row.revoked_at is not None
        with pytest.raises(oauth.OAuthError, match="invalid_grant"):
            await oauth.rotate_refresh(db, refresh_token=refresh, client_id=TEST_CLIENT_ID)


async def test_reconsent_mints_a_new_grant_id(client) -> None:
    ctx, _body = await _ctx(client)
    old_grant_id = ctx.grant.id
    create_mcp_access_token(ctx.grant)  # minted tokens must stay dead

    async with open_session() as db:
        await grant_repo.revoke_grant(db, user_id=ctx.claims.user_id, grant_id=old_grant_id)
        await db.commit()

        # The consent path resolves the same (user, client, company) triple.
        new_grant = await oauth._upsert_grant(
            db,
            user_id=ctx.claims.user_id,
            company_id=ctx.claims.company_id,
            client_id=TEST_CLIENT_ID,
            client_name=TEST_CLIENT_NAME,
            scopes=SCOPES,
        )
        await db.commit()

        assert new_grant.id != old_grant_id
        assert new_grant.revoked_at is None
        # The old grant row is gone — its access token can never validate again.
        assert await grant_repo.get_active_grant(db, old_grant_id) is None


# --- B2: refresh binding + reuse detection -------------------------------------


async def test_refresh_requires_the_grants_client_id(client) -> None:
    ctx, _body = await _ctx(client)
    async with open_session() as db:
        refresh = await oauth._mint_refresh(db, ctx.grant)
        await db.commit()
        with pytest.raises(oauth.OAuthError) as exc:
            await oauth.rotate_refresh(
                db, refresh_token=refresh, client_id="https://evil.example/x.json"
            )
        assert exc.value.error == "invalid_client"


async def test_refresh_without_client_id_is_rejected(client) -> None:
    """OAuth 2.1 — a public client must identify itself on every token request."""
    ctx, _body = await _ctx(client)
    async with open_session() as db:
        refresh = await oauth._mint_refresh(db, ctx.grant)
        await db.commit()
        with pytest.raises(oauth.OAuthError) as exc:
            await oauth.rotate_refresh(db, refresh_token=refresh, client_id=None)
        assert exc.value.error == "invalid_request"

    res = await client.post(
        "/api/oauth/token", data={"grant_type": "refresh_token", "refresh_token": refresh}
    )
    assert res.status_code == 400
    assert res.json()["error"] == "invalid_request"


async def test_reusing_a_rotated_refresh_kills_the_family(client) -> None:
    ctx, _body = await _ctx(client)
    async with open_session() as db:
        first = await oauth._mint_refresh(db, ctx.grant)
        await db.commit()
        rotated = await oauth.rotate_refresh(db, refresh_token=first, client_id=TEST_CLIENT_ID)
        second = rotated.refresh_token
        await db.commit()

        # Presenting the already-rotated token → reuse detected, family dies.
        with pytest.raises(oauth.OAuthError, match="invalid_grant"):
            await oauth.rotate_refresh(db, refresh_token=first, client_id=TEST_CLIENT_ID)
        await db.commit()

        with pytest.raises(oauth.OAuthError, match="invalid_grant"):
            await oauth.rotate_refresh(db, refresh_token=second, client_id=TEST_CLIENT_ID)


# --- B1: member cap at every turn boundary --------------------------------------


async def _capped_member_ctx(client, *, limit: int = 100, used: int = 150):
    """A member joined to an owner's company, over the monthly cap."""
    owner = await register_user(client, email="cap-owner@example.com")
    company_id = uuid.UUID(owner["user"]["organizations"][0]["id"])
    member = await register_user(client, email="cap-member@example.com")
    user_id = uuid.UUID(member["user"]["id"])
    async with open_session() as db:
        membership = await join_org(db, user_id=user_id, company_id=company_id, role="member")
        membership.monthly_token_limit = limit
        db.add(
            LlmCallRecord(
                caller="node:reviewer",
                node="reviewer",
                kind="chat_json",
                tier="strong",
                model="gpt-test",
                status="ok",
                latency_ms=10,
                prompt_tokens=used,
                completion_tokens=0,
                total_tokens=used,
                system_prompt="sys",
                user_prompt="usr",
                response_text="{}",
                parse_ok=True,
                fallback_used=False,
                user_id=user_id,
                company_id=company_id,
                key_source="env",
            )
        )
        await db.commit()
    grant = await _grant(user_id, company_id)
    claims = McpAccessClaims(
        user_id=user_id, company_id=company_id, grant_id=grant.id, scopes=list(grant.scopes or [])
    )
    return McpContext(claims=claims, grant=grant, user=None)


async def test_cap_refusal_leaves_no_orphan_session(client) -> None:
    ctx = await _capped_member_ctx(client)
    with pytest.raises(MemberTokenLimitExceeded):
        await tools.start_post_draft(ctx, StartPostDraftArgs(brief="中秋推廣"))
    async with open_session() as db:
        count = await db.scalar(
            select(func.count()).select_from(Session).where(Session.user_id == ctx.claims.user_id)
        )
        assert count == 0


async def test_auto_drive_rechecks_cap_at_every_gate(client, monkeypatch) -> None:
    ctx, _body = await _ctx(client, scopes=["knowledge:read", "drafts:write", "images:generate"])
    set_session_graph(ParkingSessionGraph())

    calls = 0
    real = tools.enforce_member_token_limit

    async def counted(db, session, user_id):
        nonlocal calls
        calls += 1
        return await real(db, session, user_id)

    monkeypatch.setattr(tools, "enforce_member_token_limit", counted)

    result = await tools.start_post_draft(ctx, StartPostDraftArgs(brief="中秋推廣", auto=True))
    task = tools._pending_turns.get(uuid.UUID(str(result["session_id"])))
    if task is not None:  # may already be done + popped by _on_turn_done
        await asyncio.wait_for(asyncio.shield(task), timeout=30)

    # start turn + angle gate + image gate — each a turn boundary.
    assert calls == 3

    # §11 — auto_picks records the *effective* values.
    async with open_session() as db:
        session = await repos.get_session(db, uuid.UUID(str(result["session_id"])))
        picks = (session.origin or {}).get("auto_picks") or {}
        assert picks["angle_index"] == STUB_RECOMMENDED_ANGLE
        assert picks["image_approved"] is True
    tools._pending_turns.clear()
    tools._pending_grants.clear()


# --- B1: draft status mapping ---------------------------------------------------


async def test_pending_spawn_reports_running_not_ready(client) -> None:
    ctx, _body = await _ctx(client)
    async with open_session() as db:
        session = await repos.create_session(
            db, user_id=ctx.claims.user_id, company_id=ctx.claims.company_id
        )
        await db.commit()
        sid = session.id

    pending = asyncio.get_running_loop().create_task(asyncio.sleep(60))
    tools._pending_turns[sid] = pending
    try:
        result = await tools.get_post_draft(ctx, SessionToolArgs(session_id=sid))
        assert result["status"] == "running"
    finally:
        pending.cancel()
        tools._pending_turns.pop(sid, None)


async def test_turn_failure_reports_failed(client) -> None:
    ctx, _body = await _ctx(client)
    async with open_session() as db:
        session = await repos.create_session(
            db, user_id=ctx.claims.user_id, company_id=ctx.claims.company_id
        )
        session.state = {"mcp_turn_error": "Session turn already in progress"}
        await db.commit()
        sid = session.id
    result = await tools.get_post_draft(ctx, SessionToolArgs(session_id=sid))
    assert result["status"] == "failed"
    assert "in progress" in result["error"]


async def test_manual_edit_after_failed_turn_reports_ready(client) -> None:
    """A non-turn edit (no state rebuild) bumps the revision past the failure."""
    ctx, _body = await _ctx(client)
    async with open_session() as db:
        session = await repos.create_session(
            db, user_id=ctx.claims.user_id, company_id=ctx.claims.company_id
        )
        session.mode = MODE_PREVIEW
        session.state = {"revision": 0}
        await db.commit()
        sid = session.id

    await tools._record_turn_error(sid, RuntimeError("provider down"))
    failed = await tools.get_post_draft(ctx, SessionToolArgs(session_id=sid))
    assert failed["status"] == "failed"

    async with open_session() as db:
        session = await repos.get_session(db, sid)
        await service.update_session_draft(db, session, caption="中秋快樂", hashtags=[], cta="")
        await db.commit()

    result = await tools.get_post_draft(ctx, SessionToolArgs(session_id=sid))
    assert result["status"] == "ready"


async def test_ready_carries_the_latest_assistant_message(client) -> None:
    """A question asked after the preview exists must not be hidden by `ready`."""
    ctx, _body = await _ctx(client)
    async with open_session() as db:
        session = await repos.create_session(
            db, user_id=ctx.claims.user_id, company_id=ctx.claims.company_id
        )
        session.mode = MODE_PREVIEW
        session.state = {"revision": 0}
        await db.flush()
        await service.update_session_draft(db, session, caption="中秋快樂", hashtags=[], cta="")
        db.add(SessionMessage(session_id=session.id, role="assistant", content="要唔要加優惠碼？"))
        await db.commit()
        sid = session.id

    result = await tools.get_post_draft(ctx, SessionToolArgs(session_id=sid))
    assert result["status"] == "ready"
    assert result["message"] == "要唔要加優惠碼？"


async def test_no_park_no_preview_reports_awaiting_reply(client) -> None:
    ctx, _body = await _ctx(client)
    async with open_session() as db:
        session = await repos.create_session(
            db, user_id=ctx.claims.user_id, company_id=ctx.claims.company_id
        )
        await db.flush()
        db.add(SessionMessage(session_id=session.id, role="assistant", content="想推廣邊類產品？"))
        await db.commit()
        sid = session.id
    result = await tools.get_post_draft(ctx, SessionToolArgs(session_id=sid))
    assert result["status"] == "awaiting_reply"
    assert result["message"] == "想推廣邊類產品？"


async def test_revise_while_turn_in_flight_is_a_tool_error(client) -> None:
    ctx, _body = await _ctx(client)
    async with open_session() as db:
        session = await repos.create_session(
            db, user_id=ctx.claims.user_id, company_id=ctx.claims.company_id
        )
        await db.commit()
        sid = session.id

    pending = asyncio.get_running_loop().create_task(asyncio.sleep(60))
    tools._pending_turns[sid] = pending
    try:
        with pytest.raises(ToolRefusal) as exc:
            await tools.revise_post_draft(
                ctx, RevisePostDraftArgs(session_id=sid, instruction="再口语化啲")
            )
        assert exc.value.reason == "turn_in_flight"
    finally:
        pending.cancel()
        tools._pending_turns.pop(sid, None)


async def test_concurrent_grant_cap_refuses_extra_drafts(client) -> None:
    ctx, _body = await _ctx(client)
    holders = []
    try:
        for _ in range(tools.GRANT_MAX_CONCURRENT):
            sid = uuid.uuid4()
            task = asyncio.get_running_loop().create_task(asyncio.sleep(60))
            tools._pending_turns[sid] = task
            tools._pending_grants[sid] = ctx.claims.grant_id
            holders.append((sid, task))
        with pytest.raises(ToolRefusal) as exc:
            await tools.start_post_draft(ctx, StartPostDraftArgs(brief="中秋推廣"))
        assert exc.value.reason == "rate_limited"
    finally:
        for sid, task in holders:
            task.cancel()
            tools._pending_turns.pop(sid, None)
            tools._pending_grants.pop(sid, None)


# --- B2: OAuth error shape + headers + last_used_at -----------------------------


async def test_token_endpoint_errors_are_rfc6749_shaped(client) -> None:
    res = await client.post("/api/oauth/token", data={"grant_type": "bogus"})
    assert res.status_code == 400
    body = res.json()
    assert body["error"] == "unsupported_grant_type"
    assert "detail" not in body
    assert res.headers["cache-control"] == "no-store"


async def test_last_used_at_is_committed(client) -> None:
    ctx, _body = await _ctx(client)
    token, _ = create_mcp_access_token(ctx.grant)
    res = await client.post(
        "/api/mcp",
        json=rpc_body("tools/list"),
        headers=rpc_headers("tools/list", token=token),
    )
    assert res.status_code == 200, res.text
    async with open_session() as db:
        grant = await grant_repo.get_active_grant(db, ctx.grant.id)
        assert grant.last_used_at is not None


async def test_notification_gets_http_202(client) -> None:
    ctx, _body = await _ctx(client)
    token, _ = create_mcp_access_token(ctx.grant)
    res = await client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=rpc_headers("notifications/initialized", token=token),
    )
    assert res.status_code == 202
