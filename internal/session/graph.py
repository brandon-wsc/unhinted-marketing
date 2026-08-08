"""Compile the session LangGraph (CHAT → AGENT → PREVIEW + revise loop)."""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from internal.llm import recorder
from internal.session import nodes as N
from internal.session.state import SessionState

logger = logging.getLogger(__name__)

# Nodes that pause for human OK before image plan (ROADMAP interrupt contract).
INTERRUPT_BEFORE = ["executor_image_plan"]

_compiled_graph: Any | None = None


def _with_llm_record_context(name: str, fn: Any) -> Any:
    """ADR 0005: correlate every LLM call in this node with session/user/company."""

    @wraps(fn)
    async def wrapped(state: SessionState) -> dict[str, Any]:
        with recorder.call_context(
            caller=f"node:{name}",
            node=name,
            session_id=state.get("thread_id"),
            user_id=state.get("user_id"),
            company_id=state.get("company_id"),
        ):
            return await fn(state)

    return wrapped


async def _wrap_reviewer_fail(state: SessionState) -> dict[str, Any]:
    """Increment attempts when leaving reviewer toward edit_copy on fail."""
    if state.get("reviewer_passed", False):
        return {}
    return N.bump_review_attempt(state)


def build_session_graph(*, checkpointer: Any | None = None):
    """Build and compile the session graph.

    Prefer AsyncPostgresSaver from lifespan (thread_id = session.id).
    MemorySaver is only for local scripts/tests when no checkpointer is passed.
    """
    g: StateGraph = StateGraph(SessionState)

    # LLM nodes get an ADR 0005 record context; non-LLM nodes stay plain.
    g.add_node("fast_rule_checker", N.fast_rule_checker)
    g.add_node("route_intent", _with_llm_record_context("route_intent", N.route_intent))
    g.add_node(
        "query_generator", _with_llm_record_context("query_generator", N.query_generator)
    )
    g.add_node("research_ingest", N.research_ingest)
    g.add_node("load_context", N.load_context)
    g.add_node("trend_searcher", _with_llm_record_context("trend_searcher", N.trend_searcher))
    g.add_node("brainstormer", _with_llm_record_context("brainstormer", N.brainstormer))
    g.add_node("executor_post", _with_llm_record_context("executor_post", N.executor_post))
    g.add_node("grounding_check", N.grounding_check)
    g.add_node("reviewer", _with_llm_record_context("reviewer", N.reviewer))
    g.add_node("edit_copy", _with_llm_record_context("edit_copy", N.edit_copy))
    g.add_node(
        "executor_image_plan",
        _with_llm_record_context("executor_image_plan", N.executor_image_plan),
    )
    g.add_node(
        "executor_image_gen",
        _with_llm_record_context("executor_image_gen", N.executor_image_gen),
    )
    g.add_node("persist_preview", N.persist_preview)
    g.add_node("chat", _with_llm_record_context("chat", N.chat))
    g.add_node("ack_confirm", _with_llm_record_context("ack_confirm", N.ack_confirm))
    g.add_node("review_exhausted", N.review_exhausted)
    g.add_node("_reviewer_fail_bump", _wrap_reviewer_fail)

    g.add_edge(START, "fast_rule_checker")
    g.add_edge("fast_rule_checker", "route_intent")
    g.add_conditional_edges(
        "route_intent",
        N.route_after_intent,
        {
            "query_generator": "query_generator",
            "load_context": "load_context",
            "edit_copy": "edit_copy",
            "ack_confirm": "ack_confirm",
            "chat": "chat",
        },
    )
    g.add_edge("query_generator", "research_ingest")
    g.add_conditional_edges(
        "research_ingest",
        N.route_after_research,
        {
            "load_context": "load_context",
            "edit_copy": "edit_copy",
            "ack_confirm": "ack_confirm",
            "chat": "chat",
        },
    )
    g.add_edge("chat", END)
    g.add_edge("ack_confirm", END)

    g.add_edge("load_context", "trend_searcher")
    g.add_edge("trend_searcher", "brainstormer")
    g.add_edge("brainstormer", "executor_post")
    g.add_edge("executor_post", "grounding_check")
    g.add_edge("grounding_check", "reviewer")
    g.add_edge("edit_copy", "grounding_check")

    g.add_conditional_edges(
        "reviewer",
        N.route_after_reviewer,
        {
            "edit_copy": "_reviewer_fail_bump",
            "executor_image_plan": "executor_image_plan",
            "persist_preview": "persist_preview",
            "review_exhausted": "review_exhausted",
        },
    )
    g.add_edge("_reviewer_fail_bump", "edit_copy")
    g.add_edge("review_exhausted", END)

    g.add_edge("executor_image_plan", "executor_image_gen")
    g.add_edge("executor_image_gen", "persist_preview")
    g.add_edge("persist_preview", END)

    saver = checkpointer if checkpointer is not None else MemorySaver()
    return g.compile(checkpointer=saver, interrupt_before=INTERRUPT_BEFORE)


def set_session_graph(graph: Any | None) -> None:
    global _compiled_graph
    _compiled_graph = graph


def get_session_graph():
    """Return the process graph (Postgres checkpointer after API lifespan)."""
    global _compiled_graph
    if _compiled_graph is None:
        logger.warning("Session graph not initialized — using in-memory checkpointer")
        _compiled_graph = build_session_graph(checkpointer=MemorySaver())
    return _compiled_graph
