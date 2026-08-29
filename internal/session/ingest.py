"""Tavily ∪ PostgreSQL ingest — shared by research_ingest and the research agent tool."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory.repos import upsert_signal
from internal.perception.tavily import search_tavily

logger = logging.getLogger(__name__)

MAX_QUERIES = 3
MAX_HITS_PER_QUERY = 5

SearchFn = Callable[..., Awaitable[list[dict[str, Any]]]]
UpsertFn = Callable[..., Awaitable[Any]]


def normalize_tavily_topic(topic: str | None) -> str:
    value = str(topic or "news")
    return value if value in ("general", "news", "finance") else "news"


def normalize_tavily_time_range(time_range: str | None) -> str:
    value = time_range or "week"
    return value if value in ("day", "week", "month", "year") else "week"


def signal_slices(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tool return: ids + short fields, never full pages."""
    slices: list[dict[str, Any]] = []
    for item in items:
        metrics = item.get("metrics") or {}
        excerpt = item.get("excerpt")
        if isinstance(excerpt, str) and len(excerpt) > 400:
            excerpt = excerpt[:397] + "…"
        slices.append(
            {
                "signal_id": item.get("signal_id"),
                "title": item.get("title"),
                "excerpt": excerpt,
                "metrics": {"query": metrics.get("query")},
            }
        )
    return slices


async def fetch_and_upsert_tavily(
    db: AsyncSession,
    queries: list[str],
    *,
    topic: str = "news",
    time_range: str = "week",
    max_results: int = MAX_HITS_PER_QUERY,
    search: SearchFn | None = None,
    upsert: UpsertFn | None = None,
) -> list[dict[str, Any]]:
    """Run each atomic query via Tavily and upsert into ``raw_news_events``."""
    search_fn = search or search_tavily
    upsert_fn = upsert or upsert_signal
    topic_s = normalize_tavily_topic(topic)
    range_s = normalize_tavily_time_range(time_range)
    capped = [
        q.strip()[:200]
        for q in queries[:MAX_QUERIES]
        if isinstance(q, str) and q.strip()
    ]

    tavily_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for query in capped:
        batch = await search_fn(
            query,
            max_results=max_results,
            topic=topic_s,
            time_range=range_s,
        )
        for item in batch:
            sid = item.get("signal_id")
            if not sid or sid in seen_ids:
                continue
            seen_ids.add(sid)
            metrics = dict(item.get("metrics") or {})
            metrics["query"] = query[:200]
            tavily_items.append({**item, "metrics": metrics})

    for item in tavily_items:
        try:
            await upsert_fn(
                db,
                signal_id=item["signal_id"],
                source=item["source"],
                title=item["title"],
                url=item.get("url"),
                excerpt=item.get("excerpt"),
                metrics=item.get("metrics") or {},
            )
        except Exception:
            logger.exception("failed to upsert Tavily signal %s", item.get("signal_id"))
    if tavily_items:
        try:
            await db.commit()
        except Exception:
            logger.exception("commit after Tavily upsert failed")
            await db.rollback()
    return tavily_items


def merge_pg_and_tavily(
    tavily_items: list[dict[str, Any]],
    pg_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prefer freshly ingested Tavily rows, then fill from PostgreSQL."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in tavily_items:
        sid = item.get("signal_id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        merged.append(
            {
                "signal_id": sid,
                "source": item["source"],
                "title": item["title"],
                "excerpt": item.get("excerpt"),
                "metrics": item.get("metrics") or {},
            }
        )
    for row in pg_rows:
        sid = row.get("signal_id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        merged.append(row)
    return merged
