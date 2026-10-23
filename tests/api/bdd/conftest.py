"""Sync bridge for pytest-bdd steps over the async API fixtures.

pytest-bdd executes step functions synchronously — pytest's
``call_fixture_func`` does not await, so ``async def`` steps silently
become un-awaited coroutines. pytest-asyncio still resolves the async
fixture chain (``client``, ``app``, ``clean_db``) for sync tests, so
steps stay sync and drive HTTP through ``api``, which runs coroutines
on the test's event loop via ``run_until_complete``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient, Response


@dataclass
class BddApi:
    """Sync facade over the async ``client`` fixture for step functions."""

    client: AsyncClient
    loop: asyncio.AbstractEventLoop

    def run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return self.loop.run_until_complete(coro)

    def request(self, method: str, path: str, **kwargs: Any) -> Response:
        return self.run(self.client.request(method, path, **kwargs))

    def get(self, path: str, **kwargs: Any) -> Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Response:
        return self.request("POST", path, **kwargs)

    def mcp_rpc(self, method: str, params: dict | None = None, *, token: str | None) -> Response:
        """One JSON-RPC request to ``/api/mcp`` (ADR 0051; see tests/api/mcp_helpers.py)."""
        from tests.api.mcp_helpers import MCP_PATH, rpc_body, rpc_headers

        name = (params or {}).get("name")
        return self.post(
            MCP_PATH,
            json=rpc_body(method, params),
            headers=rpc_headers(method, name=name, token=token),
        )

    def mcp_list_tools(self, token: str | None) -> Response:
        return self.mcp_rpc("tools/list", token=token)

    def mcp_call(self, tool: str, arguments: dict, token: str | None) -> Response:
        return self.mcp_rpc("tools/call", {"name": tool, "arguments": arguments}, token=token)


@pytest.fixture
def bdd_ctx() -> dict:
    """Per-scenario state bag shared between steps."""
    return {}


@pytest.fixture
def api(client: AsyncClient) -> BddApi:
    return BddApi(client=client, loop=asyncio.get_event_loop())
