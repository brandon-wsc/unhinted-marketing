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


def _angle_resume_graph(angles: list[str] | None = None):
    """brainstormer → angle_gate park → executor_post, same edges as production."""
    visits: list[str] = []
    seen_formats: list[Any] = []
    offered = list(ANGLES if angles is None else angles)

    async def brainstormer(state: SessionState) -> dict[str, Any]:
        visits.append("brainstormer")
        return {"brief": {"angles": list(offered)}, "angle_feedback": None}

    async def executor_post(state: SessionState) -> dict[str, Any]:
        visits.append("executor_post")
        seen_formats.append(state.get("image_format"))
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
    return graph, visits, seen_formats


@pytest.mark.asyncio
async def test_angle_gate_non_match_is_feedback() -> None:
    out = await N.angle_gate(
        {"brief": {"angles": ANGLES}, "chosen_angle": FEEDBACK}
    )
    assert out == {"chosen_angle": None, "angle_feedback": FEEDBACK}


@pytest.mark.asyncio
async def test_angle_gate_index_pick_locks() -> None:
    out = await N.angle_gate({"brief": {"angles": ANGLES}, "chosen_angle": "1"})
    assert out["chosen_angle"] == ANGLES[0]
    assert out["active_persona"] is None


CATALOG = [
    {"slug": "hk_youth", "label": "年輕人", "hook": "weekend brunch"},
    {"slug": "hk_parents", "label": "家長", "hook": "school run"},
]


@pytest.mark.asyncio
async def test_angle_gate_match_locks_chosen_persona() -> None:
    out = await N.angle_gate(
        {
            "brief": {"angles": ANGLES, "persona": "hk_youth"},
            "audience_catalog": CATALOG,
            "chosen_angle": ANGLES[0],
            "chosen_persona": "hk_parents",
        }
    )
    assert out["chosen_angle"] == ANGLES[0]
    assert out["active_persona"]["slug"] == "hk_parents"


@pytest.mark.asyncio
async def test_angle_gate_match_falls_back_to_brief_persona() -> None:
    out = await N.angle_gate(
        {
            "brief": {"angles": ANGLES, "persona": "hk_youth"},
            "audience_catalog": CATALOG,
            "chosen_angle": ANGLES[1],
        }
    )
    assert out["active_persona"]["slug"] == "hk_youth"


def test_recommended_persona_prefers_sticky_pick() -> None:
    state = {
        "brief": {"angles": ANGLES, "persona": "hk_youth"},
        "audience_catalog": CATALOG,
        "chosen_persona": "hk_parents",
    }
    payload = N.angle_pick_payload(state)
    assert payload["recommended_persona"] == "hk_parents"
    assert [p["slug"] for p in payload["personas"]] == ["hk_youth", "hk_parents"]
    assert payload["angles"] == ANGLES


@pytest.mark.asyncio
async def test_feedback_keeps_chosen_persona() -> None:
    """Non-matching text must not wipe a bundled persona pick (ADR 0029 §5)."""
    out = await N.angle_gate(
        {
            "brief": {"angles": ANGLES},
            "audience_catalog": CATALOG,
            "chosen_angle": FEEDBACK,
            "chosen_persona": "hk_parents",
        }
    )
    assert out == {"chosen_angle": None, "angle_feedback": FEEDBACK}
    assert "chosen_persona" not in out


@pytest.mark.asyncio
async def test_feedback_update_state_still_runs_angle_gate() -> None:
    """UAT 2026-09-17: Other text must not skip the gate via brainstormer edges."""
    graph, visits, _seen = _angle_resume_graph()
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
    graph, visits, _seen = _angle_resume_graph()
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


# --- ADR 0030 — image_format rides the bundled card -------------------------


def test_angle_pick_payload_carries_image_format() -> None:
    payload = N.angle_pick_payload({"brief": {"angles": ANGLES}})
    assert payload["image_format_options"] == ["single", "comic_4panel"]
    assert payload["recommended_image_format"] == "single"


def test_recommended_image_format_prefers_sticky_pick() -> None:
    payload = N.angle_pick_payload(
        {
            "brief": {"angles": ANGLES},
            "image_format": "single",
            "chosen_image_format": "comic_4panel",
        }
    )
    assert payload["recommended_image_format"] == "comic_4panel"


def test_recommended_image_format_falls_back_to_state() -> None:
    payload = N.angle_pick_payload(
        {"brief": {"angles": ANGLES}, "image_format": "comic_4panel"}
    )
    assert payload["recommended_image_format"] == "comic_4panel"


@pytest.mark.asyncio
async def test_angle_gate_match_locks_image_format() -> None:
    """Matched pick resolves chosen_image_format → image_format and clears it."""
    out = await N.angle_gate(
        {
            "brief": {"angles": ANGLES},
            "chosen_angle": ANGLES[0],
            "chosen_image_format": "comic_4panel",
        }
    )
    assert out["image_format"] == "comic_4panel"
    assert out["chosen_image_format"] is None


@pytest.mark.asyncio
async def test_angle_gate_match_without_format_pick_keeps_state() -> None:
    """Omit ≠ reset (ADR 0030 §2) — no pick means image_format is untouched."""
    out = await N.angle_gate({"brief": {"angles": ANGLES}, "chosen_angle": ANGLES[0]})
    assert "image_format" not in out
    assert "chosen_image_format" not in out


@pytest.mark.asyncio
async def test_feedback_keeps_chosen_image_format() -> None:
    """Non-matching text must not wipe a bundled format pick (ADR 0030 §4)."""
    out = await N.angle_gate(
        {
            "brief": {"angles": ANGLES},
            "chosen_angle": FEEDBACK,
            "chosen_image_format": "comic_4panel",
        }
    )
    assert out == {"chosen_angle": None, "angle_feedback": FEEDBACK}
    assert "chosen_image_format" not in out
    assert "image_format" not in out


@pytest.mark.asyncio
async def test_typed_format_words_are_angle_feedback_only() -> None:
    """ADR 0030 §3 — typed「4格漫畫」while parked is feedback, never a format pick."""
    graph, visits, _seen = _angle_resume_graph()
    config = {"configurable": {"thread_id": "angle-typed-format"}}

    await graph.ainvoke({"messages": [{"role": "user", "content": "推廣咖啡店"}]}, config)
    await graph.aupdate_state(config, {"chosen_angle": "想睇4格漫畫"})
    await graph.ainvoke(None, config)
    snap = await graph.aget_state(config)
    assert "executor_post" not in visits
    assert not snap.values.get("image_format")


@pytest.mark.asyncio
async def test_card_pick_with_format_locks_before_draft() -> None:
    graph, visits, seen = _angle_resume_graph()
    config = {"configurable": {"thread_id": "angle-format-pick"}}

    await graph.ainvoke({"messages": [{"role": "user", "content": "推廣咖啡店"}]}, config)
    await graph.aupdate_state(
        config, {"chosen_angle": ANGLES[0], "chosen_image_format": "comic_4panel"}
    )
    await graph.ainvoke(None, config)
    snap = await graph.aget_state(config)
    assert visits == ["brainstormer", "executor_post"]
    assert seen == ["comic_4panel"]
    assert snap.values["image_format"] == "comic_4panel"
    assert not snap.values.get("chosen_image_format")


@pytest.mark.asyncio
async def test_single_angle_brief_still_parks() -> None:
    """ADR 0030 §7 — a 1-angle brief parks for confirm; no fast path."""
    graph, visits, _seen = _angle_resume_graph(angles=["唯一角度"])
    config = {"configurable": {"thread_id": "angle-single"}}

    await graph.ainvoke({"messages": [{"role": "user", "content": "推廣咖啡店"}]}, config)
    snap = await graph.aget_state(config)
    assert snap.next == ("angle_gate",)
    assert visits == ["brainstormer"]
