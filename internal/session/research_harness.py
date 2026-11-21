"""Research inner loop for query_generator — ``create_agent`` (ADR 0061).

Narrow agent: ingest via the existing Tavily∪PG adapter, then QueryGenOut.
Publish-class tools are never registered. Graph vertices stay unchanged.
``QueryGenOut`` rides the loop via ``ToolStrategy`` — the model finishes
by "calling" it in the same model call.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool

from internal.llm.router import LlmProviderError, ModelTier
from internal.memory.repos import list_top_signals
from internal.session import harness as H
from internal.session import ingest as ingest_mod
from internal.session import prompts
from internal.session.context import get_db
from internal.session.fast_rules import (
    QUERY_SOURCE_FALLBACK,
    QUERY_SOURCE_LLM,
    fallback_search_queries,
    polish_search_queries,
)
from internal.session.io import QueryGenOut
from internal.session.tiers import NODE_MODEL_TIERS

RESEARCH_TOOL_NAMES = frozenset({"ingest_web_search", "query_market_trends"})

_model_override: BaseChatModel | None = None


@dataclass
class ResearchDeps:
    ingested: list[dict[str, Any]] = field(default_factory=list)
    queries_run: list[str] = field(default_factory=list)


def set_research_model_override(model: BaseChatModel | None) -> None:
    """Test hook: inject a scripted chat model. Pass None to restore live."""
    global _model_override
    _model_override = model


async def _run_ingest_web_search(
    deps: ResearchDeps,
    query: str,
    topic: str = "news",
    time_range: str = "week",
) -> list[dict[str, Any]]:
    """Search the web via Tavily and persist hits to PostgreSQL.

    At most 3 queries this turn, 5 hits each. Returns signal slices
    (id, title, excerpt, metrics.query) — never full pages.
    """
    if len(deps.queries_run) >= ingest_mod.MAX_QUERIES:
        return []
    q = (query or "").strip()[:200]
    if not q:
        return []
    key = q.lower()
    if any(existing.lower() == key for existing in deps.queries_run):
        return []
    try:
        db = get_db()
    except RuntimeError:
        return [{"error": "no_session_db"}]
    deps.queries_run.append(q)
    errors: list[str] = []
    items = await ingest_mod.fetch_and_upsert_tavily(
        db,
        [q],
        topic=topic,
        time_range=time_range,
        max_results=ingest_mod.MAX_HITS_PER_QUERY,
        errors=errors,
    )
    if errors:
        return [{"error": "tavily_failed"}]
    deps.ingested.extend(items)
    return ingest_mod.signal_slices(items)


def research_tools(deps: ResearchDeps, extra_tools: Sequence[Any] = ()) -> list[Any]:
    """LangChain tools on the research loop — publish-class names never registered."""

    @tool
    async def ingest_web_search(
        query: str,
        topic: str = "news",
        time_range: str = "week",
    ) -> str:
        """Search the web via Tavily and persist hits to PostgreSQL.

        At most 3 queries this turn, 5 hits each. Returns signal slices
        (id, title, excerpt, metrics.query) — never full pages. Returns
        ``[{"error": ...}]`` instead when the search could not run.
        """
        slices = await _run_ingest_web_search(deps, query, topic, time_range)
        return json.dumps(slices, ensure_ascii=False, default=str)

    return H.with_extra_tools([ingest_web_search, H.query_market_trends], extra_tools)


async def run_query_generator_agent(
    user_prompt: str,
    deps: ResearchDeps,
) -> QueryGenOut | None:
    """Run the research agent; return QueryGenOut or None on parse miss."""
    if _model_override is not None:
        chat, label = _model_override, H.model_label(_model_override)
    else:
        chat, label = H.live_lc_model(NODE_MODEL_TIERS["query_generator"] or ModelTier.CHEAP)
    return await H.run_typed_lc_agent(
        chat=chat,
        label=label,
        tier=NODE_MODEL_TIERS["query_generator"],
        system=prompts.QUERY_GENERATOR,
        user_prompt=user_prompt,
        tools=research_tools(deps),
        out_type=QueryGenOut,
        is_valid=lambda parsed: bool(parsed.atomic_queries()),
        log_tag="query_generator",
    )


@dataclass
class ResearchToolResult:
    """Outcome of the main agent's ``research`` tool call (ADR 0062)."""

    reply: str  # JSON string the tool returns to the main agent
    state_update: dict[str, Any] = field(default_factory=dict)


def _research_tool_error(code: str) -> ResearchToolResult:
    return ResearchToolResult(reply=json.dumps({"error": code}))


async def run_research_tool(payload: dict[str, Any]) -> ResearchToolResult:
    """Query-gen sub-agent + deterministic PG∪Tavily ingest, as one tool call.

    Mirrors ``query_generator`` → ``research_ingest``: the sub-agent may ingest
    via ``ingest_web_search`` (its items are then the Tavily contribution);
    otherwise the generated queries are searched here. The reply carries only
    what the main agent needs — queries + merged signal slices; the
    ``state_update`` mirrors ``research_ingest``'s SessionState slice so
    downstream grounding sees identical shape.
    """
    try:
        db = get_db()
    except RuntimeError:
        return _research_tool_error("no_session_db")

    rdeps = ResearchDeps()
    try:
        parsed = await run_query_generator_agent(
            json.dumps(payload, ensure_ascii=False), rdeps
        )
    except LlmProviderError:
        return _research_tool_error("research_unavailable")

    research = dict(payload.get("research") or {})
    queries = polish_search_queries(parsed.atomic_queries()) if parsed else []
    if queries:
        query_source = QUERY_SOURCE_LLM
        topic_s = ingest_mod.normalize_tavily_topic(parsed.topic)
        range_s = ingest_mod.normalize_tavily_time_range(parsed.time_range)
    else:
        query_source = QUERY_SOURCE_FALLBACK
        topic_s, range_s = "news", "week"
        entity = str(payload.get("entity_surface") or "").strip()
        queries = fallback_search_queries(
            entity, str(payload.get("fallback_hint") or "")
        )
    queries = queries[: ingest_mod.MAX_QUERIES]

    tavily_errors: list[str] = []
    if rdeps.queries_run:
        tavily_items = [
            item
            for item in rdeps.ingested
            if isinstance(item, dict) and item.get("signal_id")
        ]
    else:
        tavily_items = await ingest_mod.fetch_and_upsert_tavily(
            db,
            queries,
            topic=topic_s,
            time_range=range_s,
            max_results=ingest_mod.MAX_HITS_PER_QUERY,
            errors=tavily_errors,
        )

    pg_signals = await list_top_signals(db, limit=20, region="HK")
    merged = ingest_mod.merge_pg_and_tavily(
        tavily_items, ingest_mod.signal_row_dicts(pg_signals)
    )

    research_out = {
        **research,
        "search_queries": queries,
        "tavily_topic": topic_s,
        "tavily_time_range": range_s,
        "query_source": query_source,
        "signals_trusted": query_source != QUERY_SOURCE_FALLBACK
        and bool(tavily_items),
    }
    if rdeps.queries_run:
        research_out["ingest_via_agent"] = True
    if tavily_errors:
        research_out["tavily_failed_queries"] = tavily_errors

    state_update = {
        "research_signals": merged[:20],
        "search_query": queries[0] if queries else "",
        "source_signal_ids": [r["signal_id"] for r in merged[:8]],
        "research": research_out,
    }
    reply = json.dumps(
        {"queries": queries, "signals": ingest_mod.signal_slices(merged[:10])},
        ensure_ascii=False,
        default=str,
    )
    return ResearchToolResult(reply=reply, state_update=state_update)
