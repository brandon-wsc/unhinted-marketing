"""ADR 0062 session_agent vertex + route — mocked LLM, no Postgres."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from internal.session import agent as SA
from internal.session import nodes as N
from internal.session import research_harness as RH
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


def _handoff_call(intent: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "handoff",
                "args": {"intent": intent},
                "id": "h1",
            }
        ],
    )


def _research_call(focus: str = "") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "research",
                "args": {"focus": focus},
                "id": "r1",
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
async def test_agent_research_tool_writes_state_then_handoff(monkeypatch) -> None:
    """research runs inline; the node merges the research_ingest-shaped slice."""
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    seen: list[dict] = []

    async def fake_research(payload: dict) -> RH.ResearchToolResult:
        seen.append(payload)
        return RH.ResearchToolResult(
            reply=json.dumps({"queries": ["hk trends"], "signals": []}),
            state_update={
                "research_signals": [{"signal_id": "s1"}],
                "search_query": "hk trends",
                "source_signal_ids": ["s1"],
                "research": {"search_queries": ["hk trends"], "query_source": "llm"},
            },
        )

    monkeypatch.setattr(RH, "run_research_tool", fake_research)
    SA.set_agent_model_override(
        _scripted(_research_call("skincare"), _handoff_call("start"), "搵到料，草擬中。")
    )
    out = await N.session_agent(_base_state(research_rule_pass=True))
    assert seen and seen[0]["focus"] == "skincare"
    assert seen[0]["last_user_message"] == "幫我做帖"
    assert out["agent_next"] == "load_context"
    assert out["intent"] == "start"
    assert out["search_query"] == "hk trends"
    assert out["source_signal_ids"] == ["s1"]
    assert out["research"]["query_source"] == "llm"
    assert out["research_signals"] == [{"signal_id": "s1"}]


@pytest.mark.asyncio
async def test_research_tool_fails_closed_when_rule_blocks(monkeypatch) -> None:
    """research_rule_pass False → deterministic refusal, sub-agent never runs."""
    called = False

    async def fake_research(payload: dict) -> RH.ResearchToolResult:
        nonlocal called
        called = True
        return RH.ResearchToolResult(reply="{}")

    monkeypatch.setattr(RH, "run_research_tool", fake_research)
    deps = SA.SessionAgentDeps(research_allowed=False, research_in={"x": 1})
    tool = next(t for t in SA.session_agent_tools(deps) if t.name == "research")
    out = json.loads(await tool.ainvoke({"focus": "hk"}))
    assert out == {"error": "research_not_allowed"}
    assert called is False
    assert deps.research_out is None


@pytest.mark.asyncio
async def test_agent_research_blocked_still_hands_off(monkeypatch) -> None:
    """Gate fails closed inside the tool; the agent may still hand off."""
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    SA.set_agent_model_override(
        _scripted(_research_call(), _handoff_call("start"), "")
    )
    out = await N.session_agent(_base_state(research_rule_pass=False))
    assert out["agent_next"] == "load_context"
    assert "research_signals" not in out


@pytest.mark.asyncio
async def test_route_after_session_agent_no_marker_goes_end() -> None:
    assert N.route_after_session_agent(_base_state(agent_next=None)) == "__end__"
    assert N.route_after_session_agent(_base_state()) == "__end__"


def test_route_after_session_agent_follows_marker() -> None:
    assert N.route_after_session_agent(_base_state(agent_next="load_context")) == (
        "load_context"
    )
    assert N.route_after_session_agent(_base_state(agent_next="edit_copy")) == (
        "edit_copy"
    )
    assert N.route_after_session_agent(_base_state(agent_next="ack_confirm")) == (
        "ack_confirm"
    )


def test_route_after_session_agent_whitelist() -> None:
    """Unknown / migrated-away markers never route — fail closed to END."""
    for marker in ("query_generator", "research_ingest", "chat", "brainstormer", "bogus"):
        assert N.route_after_session_agent(_base_state(agent_next=marker)) == "__end__"


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
    # Research moved inline: query_generator/research_ingest are legacy-only,
    # unreachable from START in the agent topology.
    assert ("query_generator", "research_ingest") in legacy
    assert ("query_generator", "research_ingest") not in agent
    # Shared downstream topology untouched in both variants.
    for edges in (legacy, agent):
        assert ("executor_image_gen", "persist_preview") in edges
