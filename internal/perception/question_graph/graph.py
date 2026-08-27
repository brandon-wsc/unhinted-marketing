"""Compile the question worker graph (ADR 0018).

Linear pipeline, no checkpointer in v1 — persistence is `recommended_questions`
+ `question_runs` / `question_node_steps`, not graph state. Each run is a fresh
invoke; a failed mid-run never resumes into a later GET.
"""

from __future__ import annotations

import logging
import uuid
from functools import wraps
from itertools import pairwise
from typing import Any

from langgraph.graph import END, START, StateGraph

from internal.llm import recorder
from internal.memory.repos import save_question_node_step
from internal.perception.question_graph import nodes as N
from internal.perception.question_graph.context import get_db
from internal.perception.question_graph.state import QuestionGraphState

logger = logging.getLogger(__name__)

_compiled_graph: Any | None = None

_STEP_SEQ = {name: i + 1 for i, (name, _fn) in enumerate(N.PIPELINE)}


def _summarize(value: Any, *, depth: int = 0) -> Any:
    """Small JSON-safe summary for step I/O records."""
    if isinstance(value, list):
        if value and isinstance(value[0], dict) and "signal_id" in value[0]:
            return [str(v.get("signal_id")) for v in value[:20]]
        if value and isinstance(value[0], dict) and "text" in value[0]:
            return [str(v.get("text"))[:120] for v in value[:20]]
        return value[:20] if depth else f"list[{len(value)}]"
    if isinstance(value, dict):
        if depth >= 1:
            return f"dict[{len(value)}]"
        return {k: _summarize(v, depth=depth + 1) for k, v in list(value.items())[:20]}
    if isinstance(value, str):
        return value[:200]
    return value


def _wrap_node(name: str, fn: Any) -> Any:
    """ADR 0005 LLM correlation (caller=node:question_*) + ADR 0018 step record."""

    @wraps(fn)
    async def wrapped(state: QuestionGraphState) -> dict[str, Any]:
        with recorder.call_context(
            caller=f"node:question_{name}",
            node=name,
            company_id=state.get("company_id"),
        ):
            out = await fn(state)
        # Trace is best-effort: step persistence must not kill the run.
        try:
            db = get_db()
            await save_question_node_step(
                db,
                run_id=uuid.UUID(str(state["run_id"])),
                seq=_STEP_SEQ.get(name, 0),
                node=name,
                input=_summarize(
                    {
                        "signals": len(state.get("signals") or []),
                        "shortlisted": len(state.get("shortlisted") or []),
                        "researched": len(state.get("researched") or []),
                        "filtered": len(state.get("filtered") or []),
                        "deep": len(state.get("deep") or []),
                    }
                ),
                output=_summarize(out),
            )
            await db.commit()
        except Exception:
            logger.warning("question step record failed for %s", name, exc_info=True)
        return out

    return wrapped


def build_question_graph():
    """Build and compile the question graph (no checkpointer — ADR 0018)."""
    g: StateGraph = StateGraph(QuestionGraphState)
    for name, fn in N.PIPELINE:
        g.add_node(name, _wrap_node(name, fn))
    names = [name for name, _fn in N.PIPELINE]
    g.add_edge(START, names[0])
    for prev, nxt in pairwise(names):
        g.add_edge(prev, nxt)
    g.add_edge(names[-1], END)
    return g.compile()


def set_question_graph(graph: Any | None) -> None:
    global _compiled_graph
    _compiled_graph = graph


def get_question_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_question_graph()
    return _compiled_graph
