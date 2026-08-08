"""Tavily Search → normalized signal dicts for PG upsert (ADR 0009)."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

import httpx

from internal.config import settings

logger = logging.getLogger(__name__)

SOURCE_TAVILY = "tavily"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or "signal"


def _signal_id(url: str | None, title: str) -> str:
    key = (url or title).strip()
    digest = hashlib.sha256(f"{SOURCE_TAVILY}:{key}".encode()).hexdigest()[:16]
    return f"{SOURCE_TAVILY}:{digest}"


def has_tavily_credentials() -> bool:
    return bool((settings.tavily_api_key or "").strip())


async def search_tavily(
    query: str,
    *,
    max_results: int = 5,
    topic: str = "news",
    time_range: str | None = "week",
) -> list[dict[str, Any]]:
    """Call Tavily /search; return upsert-ready signal dicts. Empty if no key / error."""
    q = (query or "").strip()
    if not q:
        return []
    api_key = (settings.tavily_api_key or "").strip()
    if not api_key:
        logger.info("Tavily skipped — TAVILY_API_KEY not set")
        return []

    payload: dict[str, Any] = {
        "query": q,
        "max_results": max(1, min(max_results, 20)),
        "search_depth": "basic",
        "topic": topic if topic in ("general", "news", "finance") else "news",
        "include_answer": False,
    }
    if time_range in ("day", "week", "month", "year"):
        payload["time_range"] = time_range

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                TAVILY_SEARCH_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json=payload,
            )
            res.raise_for_status()
            data = res.json()
    except Exception:
        logger.exception("Tavily search failed for query=%r", q[:80])
        return []

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []

    items: list[dict[str, Any]] = []
    for i, row in enumerate(results):
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip() or f"Tavily result {i + 1}"
        url = str(row.get("url") or "").strip() or None
        excerpt = str(row.get("content") or row.get("snippet") or "").strip() or None
        if excerpt and len(excerpt) > 800:
            excerpt = excerpt[:797] + "…"
        score = row.get("score")
        items.append(
            {
                "signal_id": _signal_id(url, title),
                "source": SOURCE_TAVILY,
                "title": title[:500],
                "url": url,
                "excerpt": excerpt,
                "metrics": {
                    "query": q[:200],
                    "rank": i + 1,
                    "score": score,
                    "slug": _slugify(title),
                },
            }
        )
    return items
