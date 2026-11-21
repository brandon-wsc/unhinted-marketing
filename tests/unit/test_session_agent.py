"""ADR 0062 session_agent vertex + route — mocked LLM, no Postgres."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from internal.session import agent as SA
from internal.session import draft_harness as DH
from internal.session import nodes as N
from internal.session import research_harness as RH
from internal.session.graph import build_session_graph
from internal.session.state import MODE_AGENT, MODE_CHAT, MODE_PREVIEW
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


def _tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id}],
    )


def _handoff_call(intent: str) -> AIMessage:
    return _tool_call("handoff", {"intent": intent}, "h1")


def _research_call(focus: str = "") -> AIMessage:
    return _tool_call("research", {"focus": focus}, "r1")


def _propose_call(notes: str = "") -> AIMessage:
    return _tool_call("propose_angles", {"notes": notes}, "p1")


def _fake_propose(brief_angles: list[str] | None = None) -> DH.ProposeAnglesResult:
    angles = brief_angles if brief_angles is not None else ["角度甲", "角度乙"]
    return DH.ProposeAnglesResult(
        reply=json.dumps({"angles": angles}),
        state_update={
            "mode": MODE_AGENT,
            "brief": {"angles": angles, "summary": "s"},
            "active_persona": "hk_gen_z",
        },
        ready=True,
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
async def test_agent_propose_then_handoff_routes_to_angle_gate(monkeypatch) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    seen: list[dict] = []

    async def fake_propose(payload: dict) -> DH.ProposeAnglesResult:
        seen.append(payload)
        return _fake_propose()

    monkeypatch.setattr(DH, "run_propose_angles", fake_propose)
    SA.set_agent_model_override(
        _scripted(_propose_call(), _handoff_call("start"), "俾你揀角度先。")
    )
    out = await N.session_agent(_base_state())
    assert seen and seen[0]["user_request"] == "幫我做帖"
    assert out["agent_next"] == "angle_gate"
    assert out["intent"] == "start"
    assert out["brief"]["angles"] == ["角度甲", "角度乙"]
    assert out["mode"] == MODE_AGENT
    assert out["messages"][-1]["content"].startswith("俾你揀")


@pytest.mark.asyncio
async def test_agent_handoff_start_guarded_without_brief(monkeypatch) -> None:
    """handoff(start) before propose_angles fails closed — agent answers instead."""
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    SA.set_agent_model_override(
        _scripted(_handoff_call("start"), "等我先諗幾個角度。")
    )
    out = await N.session_agent(_base_state())
    assert out["agent_next"] is None
    assert out["mode"] == MODE_CHAT


@pytest.mark.asyncio
async def test_agent_propose_clarify_leaves_next_unset(monkeypatch) -> None:
    """Product ambiguity → clarify reply inline, no handoff, candidates on state."""
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)

    async def fake_propose(payload: dict) -> DH.ProposeAnglesResult:
        return DH.ProposeAnglesResult(
            reply=json.dumps({"clarify": True, "candidates": [{"name": "A"}]}),
            state_update={
                "mode": MODE_AGENT,
                "product_clarify": True,
                "product_candidates": [{"name": "A"}],
            },
        )

    monkeypatch.setattr(DH, "run_propose_angles", fake_propose)
    SA.set_agent_model_override(
        _scripted(_propose_call(), "你想推邊款產品？")
    )
    out = await N.session_agent(_base_state())
    assert out["agent_next"] is None
    assert out["mode"] == MODE_CHAT
    assert out["product_clarify"] is True
    assert "brief" not in out


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

    async def fake_propose(payload: dict) -> DH.ProposeAnglesResult:
        return _fake_propose()

    monkeypatch.setattr(RH, "run_research_tool", fake_research)
    monkeypatch.setattr(DH, "run_propose_angles", fake_propose)
    SA.set_agent_model_override(
        _scripted(
            _research_call("skincare"),
            _propose_call(),
            _handoff_call("start"),
            "搵到料，草擬中。",
        )
    )
    out = await N.session_agent(_base_state(research_rule_pass=True))
    assert seen and seen[0]["focus"] == "skincare"
    assert seen[0]["last_user_message"] == "幫我做帖"
    assert out["agent_next"] == "angle_gate"
    assert out["intent"] == "start"
    assert out["search_query"] == "hk trends"
    assert out["source_signal_ids"] == ["s1"]
    assert out["research"]["query_source"] == "llm"
    assert out["research_signals"] == [{"signal_id": "s1"}]
    assert out["brief"]["angles"]


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
async def test_route_after_session_agent_no_marker_goes_end() -> None:
    assert N.route_after_session_agent(_base_state(agent_next=None)) == "__end__"
    assert N.route_after_session_agent(_base_state()) == "__end__"


def test_route_after_session_agent_follows_marker() -> None:
    briefed = _base_state(agent_next="angle_gate", brief={"angles": ["a"]})
    assert N.route_after_session_agent(briefed) == "angle_gate"
    assert N.route_after_session_agent(_base_state(agent_next="edit_copy")) == (
        "edit_copy"
    )
    assert N.route_after_session_agent(_base_state(agent_next="ack_confirm")) == (
        "ack_confirm"
    )


def test_route_after_session_agent_zero_angle_bypass() -> None:
    """0-angle brief drafts immediately — the route_after_brainstormer rule."""
    out = N.route_after_session_agent(
        _base_state(agent_next="angle_gate", brief={"angles": []})
    )
    assert out == "executor_post"
    out = N.route_after_session_agent(_base_state(agent_next="angle_gate", brief={}))
    assert out == "executor_post"


def test_route_after_session_agent_whitelist() -> None:
    """Unknown / migrated-away markers never route — fail closed to END."""
    for marker in (
        "query_generator",
        "research_ingest",
        "load_context",
        "brainstormer",
        "chat",
        "bogus",
    ):
        assert N.route_after_session_agent(_base_state(agent_next=marker)) == "__end__"


def test_route_after_angle_gate_agent() -> None:
    assert N.route_after_angle_gate_agent(_base_state(chosen_angle="a")) == (
        "executor_post"
    )
    assert N.route_after_angle_gate_agent(
        _base_state(chosen_angle=None, angle_feedback="唔好咁寫")
    ) == "session_agent"


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
    # Agent entry + re-plan edges; legacy keeps its pipeline.
    assert ("session_agent", "angle_gate") in agent
    assert ("angle_gate", "session_agent") in agent
    assert ("angle_gate", "brainstormer") in legacy
    assert ("angle_gate", "session_agent") not in legacy
    # Migrated-away vertices are unreachable from START in the agent topology.
    for gone in (
        ("query_generator", "research_ingest"),
        ("load_context", "trend_searcher"),
        ("product_matcher", "brainstormer"),
    ):
        assert gone in legacy
        assert gone not in agent
    # Shared downstream topology untouched in both variants.
    for edges in (legacy, agent):
        assert ("executor_post", "grounding_check") in edges
        assert ("executor_image_gen", "persist_preview") in edges
