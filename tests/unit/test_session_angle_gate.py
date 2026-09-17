"""ADR 0028 angle_gate — pick vs feedback, including checkpoint resume."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from internal.session import nodes as N
from internal.session.state import SessionState

ANGLES = ["收工蒸發", "節日逼爆 vs 平日有位", "唔使飲到燙嘴"]
FEEDBACK = "都唔啱，想偏溫柔少抽水啲"


def _angle_resume_graph():
    """brainstormer → angle_gate park → executor_post, same edges as production."""
    visits: list[str] = []

    async def brainstormer(state: SessionState) -> dict[str, Any]:
        visits.append("brainstormer")
        return {"brief": {"angles": list(ANGLES)}, "angle_feedback": None}

    async def executor_post(state: SessionState) -> dict[str, Any]:
        visits.append("executor_post")
        return {"draft": {"caption": str(state.get("chosen_angle") or "")}}

    g: StateGraph = StateGraph(SessionState)
    g.add_node("brainstormer", brainstormer)
    g.add_node("angle_gate", N.angle_gate)
    g.add_node("executor_post", executor_post)
    g.add_edge(START, "brainstormer")
    g.add_conditional_edges(
        "brainstormer",
        N.route_after_brainstormer,
        {"angle_gate": "angle_gate", "executor_post": "executor_post"},
    )
    g.add_conditional_edges(
        "angle_gate",
        N.route_after_angle_gate,
        {"executor_post": "executor_post", "brainstormer": "brainstormer"},
    )
    g.add_edge("executor_post", END)
    graph = g.compile(checkpointer=MemorySaver(), interrupt_before=["angle_gate"])
    return graph, visits


@pytest.mark.asyncio
async def test_angle_gate_non_match_is_feedback() -> None:
    out = await N.angle_gate(
        {"brief": {"angles": ANGLES}, "chosen_angle": FEEDBACK}
    )
    assert out == {"chosen_angle": None, "angle_feedback": FEEDBACK}


@pytest.mark.asyncio
async def test_angle_gate_index_pick_locks() -> None:
    out = await N.angle_gate({"brief": {"angles": ANGLES}, "chosen_angle": "1"})
    assert out == {"chosen_angle": ANGLES[0]}


@pytest.mark.asyncio
async def test_feedback_update_state_still_runs_angle_gate() -> None:
    """UAT 2026-09-17: Other text must not skip the gate via brainstormer edges."""
    graph, visits = _angle_resume_graph()
    config = {"configurable": {"thread_id": "angle-feedback"}}

    await graph.ainvoke({"messages": [{"role": "user", "content": "推廣咖啡店"}]}, config)
    snap = await graph.aget_state(config)
    assert snap.next == ("angle_gate",)
    assert visits == ["brainstormer"]

    await graph.aupdate_state(config, {"chosen_angle": FEEDBACK})
    snap = await graph.aget_state(config)
    assert snap.next == ("angle_gate",)

    await graph.ainvoke(None, config)
    snap = await graph.aget_state(config)
    assert visits == ["brainstormer", "brainstormer"]
    assert "executor_post" not in visits
    assert snap.next == ("angle_gate",)
    assert not (snap.values.get("chosen_angle") or "").strip()
    assert (snap.values.get("draft") or {}).get("caption") != FEEDBACK


@pytest.mark.asyncio
async def test_matching_update_state_drafts_locked_angle() -> None:
    graph, visits = _angle_resume_graph()
    config = {"configurable": {"thread_id": "angle-pick"}}

    await graph.ainvoke({"messages": [{"role": "user", "content": "推廣咖啡店"}]}, config)
    await graph.aupdate_state(config, {"chosen_angle": ANGLES[0]})
    snap = await graph.aget_state(config)
    assert snap.next == ("angle_gate",)

    await graph.ainvoke(None, config)
    snap = await graph.aget_state(config)
    assert visits == ["brainstormer", "executor_post"]
    assert snap.values["draft"]["caption"] == ANGLES[0]
    assert snap.next == ()
