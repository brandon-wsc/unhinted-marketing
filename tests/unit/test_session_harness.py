"""Pydantic AI chat harness (ADR 0019) — TestModel, allowlist, cancel, SSE deltas."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel

from internal.session import harness as H
from internal.session import nodes as N
from internal.session.trace import node_trace_recording
from tests.unit.test_session_nodes import _base_state


@pytest.fixture(autouse=True)
def _clear_chat_model_override() -> None:
    H.set_chat_model_override(None)
    yield
    H.set_chat_model_override(None)


def test_chat_agent_allowlist_excludes_publish() -> None:
    agent = H.build_chat_agent(model=TestModel(call_tools=[], custom_output_text="x"))
    names = H.registered_function_tool_names(agent)
    assert names == H.CHAT_TOOL_NAMES
    assert names.isdisjoint(H.PUBLISH_TOOL_NAMES)
    assert "publish_social_post" not in names


def test_slow_probe_is_opt_in() -> None:
    prod = H.build_chat_agent(model=TestModel(call_tools=[], custom_output_text="x"))
    assert "slow_probe" not in H.registered_function_tool_names(prod)
    spiked = H.build_chat_agent(
        model=TestModel(call_tools=[], custom_output_text="x"),
        extra_tools=[H.slow_probe],
    )
    assert "slow_probe" in H.registered_function_tool_names(spiked)


@pytest.mark.asyncio
async def test_chat_node_streams_delta_with_testmodel(monkeypatch: pytest.MonkeyPatch) -> None:
    published: list[tuple[str, dict]] = []

    async def _capture(_session_id: uuid.UUID, event_type: str, data: dict | None = None) -> None:
        published.append((event_type, data or {}))

    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    monkeypatch.setattr(H.session_event_bus, "publish", _capture)
    H.set_chat_model_override(TestModel(call_tools=[], custom_output_text="你好，我可以幫你睇熱話。"))
    thread = str(uuid.uuid4())
    with node_trace_recording() as steps:
        out = await N.chat(
            _base_state(
                thread_id=thread,
                messages=[{"role": "user", "content": "你好"}],
            )
        )
    assert out["messages"][-1]["content"].startswith("你好")
    assert any(etype == "message.delta" for etype, _ in published)
    assert all(etype != "confirm.completed" for etype, _ in published)
    assert steps[-1].node == "chat"


@pytest.mark.asyncio
async def test_query_market_trends_runs_without_db() -> None:
    H.set_chat_model_override(
        TestModel(call_tools=["query_market_trends"], custom_output_text="signals noted")
    )
    text = await H.stream_chat_reply(
        user_prompt="香港最近熱話",
        session_id=None,
        deps=H.ChatDeps(),
    )
    assert text
    assert "signals" in text.lower() or "noted" in text.lower()


@pytest.mark.asyncio
async def test_stream_chat_reply_cancels_mid_slow_tool() -> None:
    started = asyncio.Event()

    async def slow_probe(_ctx: RunContext[H.ChatDeps]) -> str:
        started.set()
        await asyncio.sleep(10)
        return "slept"

    H.set_chat_model_override(TestModel(call_tools=["slow_probe"], custom_output_text="done"))
    task = asyncio.create_task(
        H.stream_chat_reply(
            user_prompt="go",
            session_id=None,
            deps=H.ChatDeps(),
            extra_tools=[slow_probe],
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_live_chat_model_uses_openai_compatible_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(H.settings, "llm_api_base", "http://127.0.0.1:4000/v1")
    monkeypatch.setattr(H.settings, "openai_api_key", "sk-test")
    model = H.live_chat_model()
    assert getattr(model, "model_name", None)
