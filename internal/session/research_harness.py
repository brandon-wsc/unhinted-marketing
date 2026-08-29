"""Pydantic AI inner loop for query_generator (ADR 0019).

Narrow agent: ingest via the existing Tavily∪PG adapter, then QueryGenOut.
Publish-class tools are never registered. Graph vertices stay unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, RunCancelled
from pydantic_ai.models import Model

from internal.llm.recorder import mark_last_call, track
from internal.llm.router import LlmProviderError, ModelTier
from internal.session import harness as H
from internal.session import ingest as ingest_mod
from internal.session import prompts
from internal.session.context import get_db
from internal.session.io import QueryGenOut, omit_nulls
from internal.session.tiers import NODE_MODEL_TIERS
from schemas.tools import QueryMarketTrendsResponse

logger = logging.getLogger(__name__)

RESEARCH_TOOL_NAMES = frozenset({"ingest_web_search", "query_market_trends"})

_model_override: Model | None = None


@dataclass
class ResearchDeps:
    ingested: list[dict[str, Any]] = field(default_factory=list)
    queries_run: list[str] = field(default_factory=list)


def set_research_model_override(model: Model | None) -> None:
    """Test hook: inject TestModel / FunctionModel. Pass None to restore live."""
    global _model_override
    _model_override = model


async def ingest_web_search(
    ctx: RunContext[ResearchDeps],
    query: str,
    topic: str = "news",
    time_range: str = "week",
) -> list[dict[str, Any]]:
    """Search the web via Tavily and persist hits to PostgreSQL.

    At most 3 queries this turn, 5 hits each. Returns signal slices
    (id, title, excerpt, metrics.query) — never full pages.
    """
    if len(ctx.deps.queries_run) >= ingest_mod.MAX_QUERIES:
        return []
    q = (query or "").strip()[:200]
    if not q:
        return []
    key = q.lower()
    if any(existing.lower() == key for existing in ctx.deps.queries_run):
        return []
    ctx.deps.queries_run.append(q)
    try:
        db = get_db()
    except RuntimeError:
        return []
    items = await ingest_mod.fetch_and_upsert_tavily(
        db,
        [q],
        topic=topic,
        time_range=time_range,
        max_results=ingest_mod.MAX_HITS_PER_QUERY,
    )
    ctx.deps.ingested.extend(items)
    return ingest_mod.signal_slices(items)


async def query_market_trends(
    ctx: RunContext[ResearchDeps],
    region: str = "HK",
    limit: int = 20,
) -> QueryMarketTrendsResponse:
    """Read-only lookup of recent Hong Kong market signals from PostgreSQL."""
    del ctx
    return await H.lookup_market_trends(region, limit)


def build_research_agent(
    *,
    model: Model,
    extra_tools: Sequence[Any] = (),
) -> Agent[ResearchDeps, QueryGenOut]:
    tools: list[Any] = [ingest_web_search, query_market_trends, *extra_tools]
    return Agent(
        model,
        deps_type=ResearchDeps,
        output_type=QueryGenOut,
        system_prompt=prompts.QUERY_GENERATOR,
        tools=tools,
        name="session_research",
        end_strategy="exhaustive",
    )


def _usage_of(result: Any) -> Any:
    usage = getattr(result, "usage", None)
    return usage() if callable(usage) else usage


async def run_query_generator_agent(
    user_prompt: str,
    deps: ResearchDeps,
) -> QueryGenOut | None:
    """Run the research agent; return QueryGenOut or None on parse miss."""
    model = _model_override or H.live_harness_model(
        NODE_MODEL_TIERS["query_generator"] or ModelTier.CHEAP
    )
    agent = build_research_agent(model=model)
    parsed: QueryGenOut | None = None
    with track(
        kind="chat_json",
        tier=NODE_MODEL_TIERS["query_generator"],
        model=H._model_label(model),
        system=prompts.QUERY_GENERATOR,
        user=user_prompt,
    ) as rec:
        try:
            result = await agent.run(user_prompt, deps=deps)
            rec.set_usage(_usage_of(result))
            output = result.output
            if isinstance(output, QueryGenOut):
                parsed = QueryGenOut.model_validate(omit_nulls(output.model_dump()))
            elif isinstance(output, dict):
                parsed = QueryGenOut.model_validate(omit_nulls(output))
            else:
                parsed = QueryGenOut.model_validate(omit_nulls({"search_query": str(output)}))
            rec.response_text = parsed.model_dump_json()
        except asyncio.CancelledError:
            raise
        except RunCancelled as exc:
            raise asyncio.CancelledError from exc
        except (ModelHTTPError, ModelAPIError) as exc:
            raise H._wrap_provider_error(exc) from exc
        except LlmProviderError:
            raise
        except Exception:
            mark_last_call(parse_ok=False, fallback_used=True)
            logger.exception("query_generator agent failed")
            return None
        if not parsed.atomic_queries():
            mark_last_call(parse_ok=False, fallback_used=True)
            return None
        mark_last_call(parse_ok=True)
        return parsed
