"""ADR 0062 session_agent vertex + route — mocked LLM, no Postgres."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from internal.session import agent as SA
from internal.session import nodes as N
from internal.session.graph import build_session_graph
from internal.session.state import MODE_CHAT, MODE_PREVIEW
from tests.unit.lc_fakes import _ScriptedChat


@pytest.fixture(autouse=True)
def _clear_agent_model_override() -> None:
    SA.set_agent_model_override(None)
    yield
    SA.set_agent_model_override(None)


def _base_state(**extra):
    state = {
        "mode": MODE_CHAT,
        "messages": [{"role": "user", "content": "幫我做帖"}],
        "company_id": "11111111-1111-1111-1111-111111111111",
        "draft": {},
        "source_signal_ids": [],
    }
    state.update(extra)
    return state


def _scripted(*msgs: AIMessage | str) -> _ScriptedChat:
    return _ScriptedChat(
        messages=iter([AIMessage(content=m) if isinstance(m, str) else m for m in msgs])
    )


def _handoff_call(intent: str, research: bool = False) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "handoff",
                "args": {"intent": intent, "research": research},
                "id": "h1",
            }
        ],
    )


@pytest.mark.asyncio
async def test_agent_replies_inline_when_no_handoff(monkeypatch) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    SA.set_agent_model_override(_scripted("好呀，最近美心個 campaign 幾好笑。"))
    out = await N.session_agent(_base_state())
    assert out["agent_next"] is None
    assert out["mode"] == MODE_CHAT
    assert out["messages"][-1]["content"].startswith("好呀")
    assert "intent" not in out


@pytest.mark.asyncio
async def test_agent_handoff_start_routes_to_load_context(monkeypatch) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    SA.set_agent_model_override(_scripted(_handoff_call("start"), "等我幫你草擬先。"))
    out = await N.session_agent(_base_state())
    assert out["agent_next"] == "load_context"
    assert out["intent"] == "start"
    # Transitional text the agent emitted is kept as a real message.
    assert out["messages"][-1]["content"].startswith("等我")
    assert "mode" not in out


@pytest.mark.asyncio
async def test_agent_handoff_revise_routes_to_edit_copy(monkeypatch) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    SA.set_agent_model_override(_scripted(_handoff_call("revise"), ""))
    out = await N.session_agent(
        _base_state(mode=MODE_PREVIEW, draft={"caption": "old"})
    )
    assert out["agent_next"] == "edit_copy"
    assert out["intent"] == "revise"
    assert "messages" not in out


@pytest.mark.asyncio
async def test_agent_handoff_confirm_routes_to_ack_confirm(monkeypatch) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    SA.set_agent_model_override(_scripted(_handoff_call("confirm_intent"), ""))
    out = await N.session_agent(_base_state(mode=MODE_PREVIEW, draft={"caption": "x"}))
    assert out["agent_next"] == "ack_confirm"
    assert out["intent"] == "confirm_intent"


@pytest.mark.asyncio
async def test_agent_research_handoff_routes_to_query_generator(monkeypatch) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    SA.set_agent_model_override(_scripted(_handoff_call("start", research=True), ""))
    out = await N.session_agent(_base_state())
    assert out["agent_next"] == "query_generator"
    assert out["intent"] == "start"


@pytest.mark.asyncio
async def test_route_after_session_agent_no_marker_goes_end() -> None:
    assert N.route_after_session_agent(_base_state(agent_next=None)) == "__end__"
    assert N.route_after_session_agent(_base_state()) == "__end__"


def test_route_after_session_agent_follows_marker() -> None:
    assert N.route_after_session_agent(_base_state(agent_next="load_context")) == (
        "load_context"
    )
    assert N.route_after_session_agent(
        _base_state(agent_next="query_generator", research_rule_pass=True)
    ) == "query_generator"


def test_route_after_session_agent_research_gate() -> None:
    """rule_pass False blocks a research handoff → drops to the intent vertex."""
    assert N.route_after_session_agent(
        _base_state(
            agent_next="query_generator", intent="start", research_rule_pass=False
        )
    ) == "load_context"
    assert N.route_after_session_agent(
        _base_state(
            agent_next="query_generator", intent="revise", research_rule_pass=False
        )
    ) == "edit_copy"


@pytest.mark.asyncio
async def test_agent_fallback_reply_without_llm(monkeypatch) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: False)
    out = await N.session_agent(_base_state())
    assert out["agent_next"] is None
    assert out["mode"] == MODE_CHAT
    assert out["messages"][-1]["content"]


def test_graph_topology_switch() -> None:
    legacy = {(e.source, e.target) for e in build_session_graph().get_graph().edges}
    agent = {
        (e.source, e.target)
        for e in build_session_graph(main_agent=True).get_graph().edges
    }
    assert ("thread_recap", "route_intent") in legacy
    assert ("thread_recap", "session_agent") not in legacy
    assert ("thread_recap", "session_agent") in agent
    assert ("thread_recap", "route_intent") not in agent
    # Shared downstream topology untouched in both variants.
    for edges in (legacy, agent):
        assert ("query_generator", "research_ingest") in edges
        assert ("executor_image_gen", "persist_preview") in edges
