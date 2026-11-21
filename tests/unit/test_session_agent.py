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


def _draft_post_call() -> AIMessage:
    return _tool_call("draft_post", {}, "d1")


def _revise_call() -> AIMessage:
    return _tool_call("revise_draft", {}, "e1")


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
async def test_agent_draft_post_routes_to_grounding(monkeypatch) -> None:
    """Angle picked → draft_post writes the draft; node routes to grounding."""
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    seen: list[dict] = []

    async def fake_draft(payload: dict) -> DH.DraftWriteResult:
        seen.append(payload)
        return DH.DraftWriteResult(
            reply=json.dumps({"drafted": True, "caption": "新 caption"}),
            state_update={
                "draft": {"caption": "新 caption", "hashtags": [], "cta": "x"},
                "source_signal_ids": ["s1"],
                "need_image": True,
                "grounding_ok": True,
                "chosen_angle": None,
            },
        )

    monkeypatch.setattr(DH, "run_draft_post", fake_draft)
    SA.set_agent_model_override(_scripted(_draft_post_call(), "寫緊個稿…"))
    out = await N.session_agent(
        _base_state(
            mode=MODE_AGENT,
            chosen_angle="角度甲",
            brief={"angles": ["角度甲", "角度乙"]},
        )
    )
    assert seen and seen[0]["chosen_angle"] == "角度甲"
    assert out["agent_next"] == "grounding_check"
    assert out["draft"]["caption"] == "新 caption"
    assert out["chosen_angle"] is None
    assert out["messages"][-1]["content"].startswith("寫緊")


@pytest.mark.asyncio
async def test_agent_revise_draft_routes_to_grounding(monkeypatch) -> None:
    """User edit → revise_draft; the draft flows to grounding, never a handoff."""
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    seen: list[dict] = []

    async def fake_revise(payload: dict) -> DH.DraftWriteResult:
        seen.append(payload)
        return DH.DraftWriteResult(
            reply=json.dumps({"drafted": True, "caption": "改咗 caption"}),
            state_update={
                "draft": {"caption": "改咗 caption", "hashtags": [], "cta": "x"},
                "grounding_ok": True,
            },
        )

    monkeypatch.setattr(DH, "run_revise_draft", fake_revise)
    SA.set_agent_model_override(_scripted(_revise_call(), ""))
    out = await N.session_agent(
        _base_state(mode=MODE_PREVIEW, draft={"caption": "old"})
    )
    assert seen and seen[0]["draft"]["caption"] == "old"
    assert out["agent_next"] == "grounding_check"
    assert out["draft"]["caption"] == "改咗 caption"
    assert "intent" not in out
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
    assert N.route_after_session_agent(_base_state(agent_next="grounding_check")) == (
        "grounding_check"
    )
    assert N.route_after_session_agent(_base_state(agent_next="ack_confirm")) == (
        "ack_confirm"
    )


@pytest.mark.asyncio
async def test_draft_post_refuses_unpicked_angles(monkeypatch) -> None:
    """ADR 0028: offered angles must pass the park — the tool fails closed."""
    called = False

    async def fake_draft(payload: dict) -> DH.DraftWriteResult:
        nonlocal called
        called = True
        return DH.DraftWriteResult(reply="{}")

    monkeypatch.setattr(DH, "run_draft_post", fake_draft)
    deps = SA.SessionAgentDeps(
        draft_in={"brief": {"angles": ["a", "b"]}, "chosen_angle": None}
    )
    tool = next(t for t in SA.session_agent_tools(deps) if t.name == "draft_post")
    out = await tool.ainvoke({})
    assert "unpicked" in out
    assert called is False
    assert deps.write_out is None


@pytest.mark.asyncio
async def test_draft_post_requires_brief(monkeypatch) -> None:
    deps = SA.SessionAgentDeps(draft_in={"brief": {}})
    tool = next(t for t in SA.session_agent_tools(deps) if t.name == "draft_post")
    out = await tool.ainvoke({})
    assert "no brief" in out


@pytest.mark.asyncio
async def test_draft_post_allows_zero_angle_brief(monkeypatch) -> None:
    """0-angle brief drafts directly — the route_after_brainstormer rule."""
    async def fake_draft(payload: dict) -> DH.DraftWriteResult:
        return DH.DraftWriteResult(
            reply="{}",
            state_update={"draft": {"caption": "x"}, "grounding_ok": True},
        )

    monkeypatch.setattr(DH, "run_draft_post", fake_draft)
    deps = SA.SessionAgentDeps(draft_in={"brief": {"angles": []}})
    tool = next(t for t in SA.session_agent_tools(deps) if t.name == "draft_post")
    await tool.ainvoke({})
    assert deps.write_out["draft"]["caption"] == "x"


@pytest.mark.asyncio
async def test_handoff_start_refuses_zero_angle_brief() -> None:
    """No angles → no park: the tool steers the agent to draft_post instead."""
    deps = SA.SessionAgentDeps(
        draft_ready=True, draft_out={"brief": {"angles": []}}
    )
    tool = next(t for t in SA.session_agent_tools(deps) if t.name == "handoff")
    out = await tool.ainvoke({"intent": "start"})
    assert "draft_post" in out
    assert deps.next is None


@pytest.mark.asyncio
async def test_revise_draft_requires_draft() -> None:
    deps = SA.SessionAgentDeps(draft_in={"draft": {}})
    tool = next(t for t in SA.session_agent_tools(deps) if t.name == "revise_draft")
    out = await tool.ainvoke({})
    assert "no_draft" in out


def test_route_after_fast_rules_confirm_intercept() -> None:
    """ADR 0062 — confirm flag short-circuits to ack_confirm before the agent."""
    assert N.route_after_fast_rules(_base_state(confirm_intent=True)) == (
        "ack_confirm"
    )
    assert N.route_after_fast_rules(_base_state(confirm_intent=False)) == (
        "thread_recap"
    )
    assert N.route_after_fast_rules(_base_state()) == "thread_recap"


def test_route_after_session_agent_whitelist() -> None:
    """Unknown / migrated-away markers never route — fail closed to END."""
    for marker in (
        "query_generator",
        "research_ingest",
        "load_context",
        "brainstormer",
        "edit_copy",
        "executor_post",
        "chat",
        "bogus",
    ):
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
        ("brainstormer", "angle_gate"),
        ("edit_copy", "grounding_check"),
        ("executor_post", "grounding_check"),
        ("_reviewer_fail_bump", "edit_copy"),
        ("executor_image_plan", "executor_image_gen"),
        ("reviewer", "executor_image_plan"),
    ):
        assert gone in legacy
        assert gone not in agent
    # Confirm intercept only exists in the agent topology.
    assert ("fast_rule_checker", "ack_confirm") in agent
    assert ("fast_rule_checker", "ack_confirm") not in legacy
    for edges in (legacy, agent):
        assert ("fast_rule_checker", "thread_recap") in edges
    # Agent-owned draft legs: drafts enter grounding inline; reviewer retries
    # and the image-plan hop re-enter the agent, not legacy vertices.
    assert ("session_agent", "grounding_check") in agent
    assert ("session_agent", "executor_image_gen") in agent
    assert ("session_agent", "persist_preview") in agent
    assert ("_reviewer_fail_bump", "session_agent") in agent
    assert ("reviewer", "session_agent") in agent
    # Shared downstream topology untouched in both variants.
    for edges in (legacy, agent):
        assert ("grounding_check", "reviewer") in edges
        assert ("executor_image_gen", "persist_preview") in edges
        assert ("hold_locked_plan", "executor_image_gen") in edges


def _plan_call() -> AIMessage:
    return _tool_call("plan_image", {}, "i1")


def _to_preview_call() -> AIMessage:
    return _tool_call("handoff", {"intent": "to_preview"}, "tp1")


@pytest.mark.asyncio
async def test_agent_plan_image_routes_to_gen_park(monkeypatch) -> None:
    """need_image hop → plan_image writes the plan; node parks at gen."""
    from internal.session import image_harness as IH

    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    seen: list[dict] = []

    async def fake_plan(payload: dict) -> IH.PlanImageResult:
        seen.append(payload)
        return IH.PlanImageResult(
            reply=json.dumps({"planned": True, "format": "single"}),
            state_update={
                "image_plan": {"format": "single", "prompt": "p"},
                "image_format": "single",
            },
        )

    monkeypatch.setattr(IH, "run_plan_image", fake_plan)
    SA.set_agent_model_override(_scripted(_plan_call(), ""))
    out = await N.session_agent(
        _base_state(
            mode=MODE_PREVIEW,
            draft={"caption": "cap"},
            need_image=True,
        )
    )
    assert seen and seen[0]["draft"]["caption"] == "cap"
    assert out["agent_next"] == "executor_image_gen"
    assert out["image_plan"]["prompt"] == "p"


@pytest.mark.asyncio
async def test_agent_to_preview_skips_image(monkeypatch) -> None:
    """Model decides no image → persist_preview + need_image cleared."""
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    SA.set_agent_model_override(_scripted(_to_preview_call(), ""))
    out = await N.session_agent(
        _base_state(mode=MODE_PREVIEW, draft={"caption": "cap"}, need_image=True)
    )
    assert out["agent_next"] == "persist_preview"
    assert out["need_image"] is False


@pytest.mark.asyncio
async def test_plan_image_refuses_unreviewed_draft(monkeypatch) -> None:
    """A draft written this call must pass review before image planning."""
    from internal.session import image_harness as IH

    called = False

    async def fake_plan(payload: dict) -> IH.PlanImageResult:
        nonlocal called
        called = True
        return IH.PlanImageResult(reply="{}")

    monkeypatch.setattr(IH, "run_plan_image", fake_plan)
    deps = SA.SessionAgentDeps(
        draft_in={"need_image": True, "draft": {"caption": "old"}},
        write_out={"draft": {"caption": "new"}},
    )
    tool = next(t for t in SA.session_agent_tools(deps) if t.name == "plan_image")
    out = await tool.ainvoke({})
    assert "draft_changed" in out
    assert called is False


@pytest.mark.asyncio
async def test_plan_image_refuses_reviewer_pending() -> None:
    """ADR 0062: the retry budget is not cognition — a bounced draft must be
    revised, never parked at Execute."""
    deps = SA.SessionAgentDeps(
        draft_in={
            "draft": {"caption": "x"},
            "need_image": True,
            "reviewer_feedback": "tone too salesy",
            "reviewer_passed": False,
        }
    )
    tool = next(t for t in SA.session_agent_tools(deps) if t.name == "plan_image")
    out = await tool.ainvoke({})
    assert "reviewer_pending" in out


@pytest.mark.asyncio
async def test_plan_image_requires_need_image_flag() -> None:
    deps = SA.SessionAgentDeps(
        draft_in={"need_image": False, "draft": {"caption": "x"}}
    )
    tool = next(t for t in SA.session_agent_tools(deps) if t.name == "plan_image")
    out = await tool.ainvoke({})
    assert "no_image_needed" in out


@pytest.mark.asyncio
async def test_to_preview_requires_need_image() -> None:
    deps = SA.SessionAgentDeps(draft_in={"need_image": False})
    tool = next(t for t in SA.session_agent_tools(deps) if t.name == "handoff")
    out = await tool.ainvoke({"intent": "to_preview"})
    assert "error" in out
    assert deps.next is None


@pytest.mark.asyncio
async def test_to_preview_refuses_while_image_parked() -> None:
    """Parked awaiting card can never be dropped — the model must re-plan."""
    deps = SA.SessionAgentDeps(
        draft_in={"need_image": True, "hold_image_park": True}
    )
    tool = next(t for t in SA.session_agent_tools(deps) if t.name == "handoff")
    out = await tool.ainvoke({"intent": "to_preview"})
    assert "park" in out
    assert deps.next is None


@pytest.mark.asyncio
async def test_to_preview_refuses_reviewer_pending() -> None:
    """A bounced draft cannot be persisted to preview behind the reviewer's back."""
    deps = SA.SessionAgentDeps(
        draft_in={
            "draft": {"caption": "x"},
            "need_image": True,
            "reviewer_feedback": "tone too salesy",
            "reviewer_passed": False,
        }
    )
    tool = next(t for t in SA.session_agent_tools(deps) if t.name == "handoff")
    out = await tool.ainvoke({"intent": "to_preview"})
    assert "reviewer_pending" in out
    assert deps.next is None
