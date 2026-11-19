"""Tavily adapter — failures raise TavilySearchError, never a fake empty list."""

from __future__ import annotations

import httpx
import pytest

from internal.perception import tavily


class _FailingClient:
    async def __aenter__(self) -> _FailingClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(self, *_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("down")


@pytest.mark.asyncio
async def test_search_tavily_raises_on_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tavily.settings, "tavily_api_key", "key")
    monkeypatch.setattr(
        tavily.httpx, "AsyncClient", lambda **_kwargs: _FailingClient()
    )
    with pytest.raises(tavily.TavilySearchError):
        await tavily.search_tavily("hk")


@pytest.mark.asyncio
async def test_search_tavily_empty_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No key is a deliberate skip, not a failure — stays an empty list."""
    monkeypatch.setattr(tavily.settings, "tavily_api_key", "")
    assert await tavily.search_tavily("hk") == []
