"""ADR 0056 — personal access tokens for headless MCP clients.

Pins the contract: minted PATs are ``unh_`` bearers backed by a grant, work
at ``/api/mcp`` and nowhere else, and die with the grant, expiry, or a lost
membership — never resurrected, never crossing companies.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from internal.mcp import oauth, personal_tokens
from internal.mcp.auth import McpContext, _resolve_grant
from internal.mcp.grants import get_active_grant
from internal.mcp.tokens import McpAccessClaims
from internal.memory.database import open_session
from internal.memory.models import McpPersonalToken
from tests.api.helpers import auth_header, register_user, strip_org_membership
from tests.api.mcp_helpers import rpc_body, rpc_headers


async def _mint(client, body: dict, token: str, *, expect: int = 201) -> dict | None:
    res = await client.post(
        "/api/auth/me/mcp-tokens", json=body, headers=auth_header(token)
    )
    assert res.status_code == expect, res.text
    return res.json() if expect == 201 else None


async def _register(client) -> tuple[dict, uuid.UUID, uuid.UUID]:
    body = await register_user(client)
    return (
        body,
        uuid.UUID(body["user"]["id"]),
        uuid.UUID(body["user"]["organizations"][0]["id"]),
    )


def _mint_body(company_id: uuid.UUID, **extra) -> dict:
    return {"name": "Hermes bot", "company_id": str(company_id), **extra}


async def test_mint_returns_an_unh_token_backed_by_a_grant(client) -> None:
    body, user_id, company_id = await _register(client)
    res = await _mint(client, _mint_body(company_id), body["access_token"])

    token, app = res["token"], res["app"]
    assert token.startswith(personal_tokens.PAT_PREFIX)
    assert app["kind"] == "pat"
    assert app["client_name"] == "Hermes bot"
    assert app["token_prefix"] == token[:12]
    assert app["expires_at"] is None
    assert sorted(app["scopes"]) == oauth.DEFAULT_SCOPES

    async with open_session() as db:
        grant = await get_active_grant(db, uuid.UUID(app["id"]))
        assert grant is not None
        assert grant.user_id == user_id and grant.company_id == company_id
        assert personal_tokens.is_pat_client_id(grant.client_id)
        row = await db.scalar(
            select(McpPersonalToken).where(McpPersonalToken.grant_id == grant.id)
        )
        assert row is not None and row.token_hash == oauth.hash_refresh_token(token)


async def test_pat_calls_mcp_and_bumps_last_used(client) -> None:
    body, _user_id, company_id = await _register(client)
    res = await _mint(client, _mint_body(company_id), body["access_token"])

    call = await client.post(
        "/api/mcp",
        json=rpc_body("tools/list"),
        headers=rpc_headers("tools/list", token=res["token"]),
    )
    assert call.status_code == 200, call.text

    async with open_session() as db:
        grant = await get_active_grant(db, uuid.UUID(res["app"]["id"]))
        assert grant.last_used_at is not None


async def test_pat_is_refused_everywhere_but_mcp(client) -> None:
    body, _user_id, company_id = await _register(client)
    res = await _mint(client, _mint_body(company_id), body["access_token"])

    for method, url in (
        ("GET", "/api/auth/me/connected-apps"),
        ("POST", "/api/auth/me/mcp-tokens"),
    ):
        r = await client.request(
            method, url, json=_mint_body(company_id), headers=auth_header(res["token"])
        )
        assert r.status_code == 401, (method, url, r.text)


async def test_revoking_the_grant_kills_the_pat(client) -> None:
    body, _user_id, company_id = await _register(client)
    res = await _mint(client, _mint_body(company_id), body["access_token"])

    delete = await client.delete(
        f"/api/auth/me/connected-apps/{res['app']['id']}",
        headers=auth_header(body["access_token"]),
    )
    assert delete.status_code == 204

    call = await client.post(
        "/api/mcp",
        json=rpc_body("tools/list"),
        headers=rpc_headers("tools/list", token=res["token"]),
    )
    assert call.status_code == 401


async def test_expired_pat_is_refused(client) -> None:
    body, _user_id, company_id = await _register(client)
    res = await _mint(
        client, _mint_body(company_id, expires_in_days=1), body["access_token"]
    )
    assert res["app"]["expires_at"] is not None

    async with open_session() as db:
        await db.execute(
            McpPersonalToken.__table__.update()
            .where(McpPersonalToken.token_hash == oauth.hash_refresh_token(res["token"]))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db.commit()

    call = await client.post(
        "/api/mcp",
        json=rpc_body("tools/list"),
        headers=rpc_headers("tools/list", token=res["token"]),
    )
    assert call.status_code == 401


async def test_losing_membership_kills_the_pat(client, db_session) -> None:
    body, user_id, company_id = await _register(client)
    res = await _mint(client, _mint_body(company_id), body["access_token"])

    await strip_org_membership(db_session, user_id=user_id)

    call = await client.post(
        "/api/mcp",
        json=rpc_body("tools/list"),
        headers=rpc_headers("tools/list", token=res["token"]),
    )
    assert call.status_code == 401


async def test_mint_validates_membership_scopes_and_cap(client) -> None:
    body, _user_id, company_id = await _register(client)
    token = body["access_token"]

    # A company the user is not a member of.
    await _mint(
        client, _mint_body(uuid.uuid4()), token, expect=403
    )
    # Bogus and non-step-up extras are refused; the default set is not a param.
    await _mint(
        client,
        _mint_body(company_id, extra_scopes=["publish:write"]),
        token,
        expect=400,
    )
    await _mint(
        client,
        _mint_body(company_id, extra_scopes=["drafts:write"]),
        token,
        expect=400,
    )
    res = await _mint(
        client,
        _mint_body(company_id, extra_scopes=["images:generate"]),
        token,
    )
    assert "images:generate" in res["app"]["scopes"]

    async with open_session() as db:
        for _ in range(personal_tokens.MAX_LIVE_PATS_PER_USER - 1):
            await personal_tokens.mint_pat(
                db,
                user_id=_user_id,
                company_id=company_id,
                name="bulk",
                scopes=list(oauth.DEFAULT_SCOPES),
                expires_at=None,
            )
        await db.commit()
    await _mint(client, _mint_body(company_id), token, expect=400)


async def test_expired_pats_do_not_eat_the_cap(client) -> None:
    body, user_id, company_id = await _register(client)
    token = body["access_token"]

    async with open_session() as db:
        for _ in range(personal_tokens.MAX_LIVE_PATS_PER_USER):
            await personal_tokens.mint_pat(
                db,
                user_id=user_id,
                company_id=company_id,
                name="bulk",
                scopes=list(oauth.DEFAULT_SCOPES),
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        await db.commit()

    await _mint(client, _mint_body(company_id), token)


async def test_pat_scopes_gate_tools_the_same_as_oauth(client) -> None:
    """A PAT without images:generate gets the same insufficient_scope 403."""
    body, _user_id, company_id = await _register(client)
    res = await _mint(client, _mint_body(company_id), body["access_token"])

    call = await client.post(
        "/api/mcp",
        json=rpc_body(
            "tools/call",
            {"name": "approve_image", "arguments": {"session_id": str(uuid.uuid4())}},
        ),
        headers=rpc_headers("tools/call", name="approve_image", token=res["token"]),
    )
    assert call.status_code == 403
    assert 'scope="images:generate"' in call.headers["www-authenticate"]


async def test_mcp_context_path_resolves_a_pat(client) -> None:
    """The dep-level shape: PAT → synthetic claims from the live grant."""
    body, user_id, company_id = await _register(client)
    res = await _mint(client, _mint_body(company_id), body["access_token"])

    async with open_session() as db:
        resolved = await _resolve_grant(db, res["token"])
        assert resolved is not None
        claims, grant = resolved
        assert claims == McpAccessClaims(
            user_id=user_id,
            company_id=company_id,
            grant_id=grant.id,
            scopes=list(grant.scopes or []),
        )
        _ = McpContext(claims=claims, grant=grant, user=None)
