"""JSON-RPC dispatch surface (internal/mcp/server.py) — ADR 0051 §8.

Handshake methods, notifications, batches, and the §13 per-grant rate
window — all pure logic, no Postgres. Tool handlers are not exercised
here; they need a live grant and are covered under tests/api/.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from internal.mcp import server
from internal.mcp.errors import ToolRefusal


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(
        claims=SimpleNamespace(
            user_id=uuid.uuid4(),
            company_id=uuid.uuid4(),
            grant_id=uuid.uuid4(),
            scopes=["knowledge:read"],
        ),
        scopes={"knowledge:read"},
    )


def _req(method: str, params: dict | None = None, rpc_id=1) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or {}}


@pytest.mark.asyncio
async def test_initialize_returns_handshake_result():
    res = await server.dispatch(_ctx(), _req("initialize"))
    result = res["result"]
    assert result["protocolVersion"] == server.PROTOCOL_VERSION
    assert result["serverInfo"]["name"]
    assert "tools" in result["capabilities"]


@pytest.mark.asyncio
async def test_ping_returns_empty_result():
    res = await server.dispatch(_ctx(), _req("ping"))
    assert res == {"jsonrpc": "2.0", "id": 1, "result": {}}


@pytest.mark.asyncio
async def test_unknown_method_is_method_not_found():
    res = await server.dispatch(_ctx(), _req("resources/list"))
    assert res["error"]["code"] == server.RPC_METHOD_NOT_FOUND


@pytest.mark.asyncio
async def test_notification_returns_none():
    body = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert await server.dispatch(_ctx(), body) is None


@pytest.mark.asyncio
async def test_batch_dispatches_requests_and_drops_notifications():
    body = [
        _req("initialize", rpc_id=1),
        _req("ping", rpc_id=2),
        {"jsonrpc": "2.0", "method": "notifications/cancelled"},
    ]
    res = await server.dispatch(_ctx(), body)
    assert isinstance(res, list) and len(res) == 2
    assert [r["id"] for r in res] == [1, 2]


@pytest.mark.asyncio
async def test_batch_of_only_notifications_returns_none():
    body = [{"jsonrpc": "2.0", "method": "notifications/a"}]
    assert await server.dispatch(_ctx(), body) is None


@pytest.mark.asyncio
async def test_empty_batch_is_invalid_request():
    res = await server.dispatch(_ctx(), [])
    assert res["error"]["code"] == server.RPC_INVALID_REQUEST


@pytest.mark.asyncio
async def test_non_rpc_body_is_invalid_request():
    res = await server.dispatch(_ctx(), {"hello": "world"})
    assert res["error"]["code"] == server.RPC_INVALID_REQUEST


def test_rate_window_allows_then_refuses(monkeypatch):
    ctx = _ctx()
    server._rate_windows.clear()
    for _ in range(server.RATE_LIMIT_MUTATING):
        server._check_grant_rate(ctx, "start_post_draft")
    with pytest.raises(ToolRefusal) as exc:
        server._check_grant_rate(ctx, "start_post_draft")
    assert exc.value.reason == "rate_limited"


def test_rate_window_ignores_read_tools():
    ctx = _ctx()
    server._rate_windows.clear()
    for _ in range(server.RATE_LIMIT_MUTATING + 5):
        server._check_grant_rate(ctx, "get_post_draft")


def test_rate_window_is_per_grant():
    ctx_a, ctx_b = _ctx(), _ctx()
    server._rate_windows.clear()
    for _ in range(server.RATE_LIMIT_MUTATING):
        server._check_grant_rate(ctx_a, "revise_post_draft")
    server._check_grant_rate(ctx_b, "revise_post_draft")  # no raise
