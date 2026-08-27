"""Ingest HK news RSS feeds as signals (ADR 0018 — zero-key timing fuel).

Feeds are public RSS: no API keys. Each feed is isolated — one dead feed
never fails the cycle. Items carry real URLs, which makes the question
graph's shallow_research hop cheaper than title-only Trends.
"""

import hashlib
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory.repos import upsert_signal

logger = logging.getLogger(__name__)

USER_AGENT = "unhinted-marketing/0.1 (+rss-ingest)"
MAX_ITEMS_PER_FEED = 30

FEEDS: list[dict[str, str]] = [
    {
        "source": "google_news_hk",
        "url": "https://news.google.com/rss?hl=zh-HK&gl=HK&ceid=HK:zh-Hant",
    },
    {
        "source": "yahoo_news_hk",
        "url": "https://hk.news.yahoo.com/rss/",
    },
]


def _signal_id(source: str, key: str) -> str:
    digest = hashlib.sha256(f"{source}:{key}".encode()).hexdigest()[:16]
    return f"{source}:{digest}"


async def fetch_feed(url: str) -> list[dict]:
    try:
        import feedparser
    except ImportError as exc:
        raise RuntimeError("feedparser is not installed") from exc

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    parsed = feedparser.parse(resp.text)
    return _entries_from_parsed(parsed)


def _entries_from_parsed(parsed: object) -> list[dict]:
    items: list[dict] = []
    for entry in getattr(parsed, "entries", [])[:MAX_ITEMS_PER_FEED]:
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        link = (entry.get("link") or "").strip() or None
        key = entry.get("id") or link or title
        summary = (entry.get("summary") or "").strip()
        items.append(
            {"key": str(key), "title": title, "url": link, "excerpt": summary[:500] or None}
        )
    return items


def parse_feed_xml(xml: str) -> list[dict]:
    """Parse RSS/Atom XML without a network fetch (tests + fetch_feed)."""
    import feedparser

    return _entries_from_parsed(feedparser.parse(xml))


async def ingest_rss_news(db: AsyncSession) -> dict[str, int]:
    """Fetch configured RSS feeds and upsert into raw_news_events."""
    counts: dict[str, int] = {feed["source"]: 0 for feed in FEEDS}
    counts["errors"] = 0
    now = datetime.now(UTC)

    for feed in FEEDS:
        source = feed["source"]
        try:
            items = await fetch_feed(feed["url"])
            for item in items:
                await upsert_signal(
                    db,
                    signal_id=_signal_id(source, item["key"]),
                    source=source,
                    title=item["title"],
                    url=item.get("url"),
                    excerpt=item.get("excerpt"),
                    metrics={"feed": source},
                    ingested_at=now,
                )
                counts[source] += 1
        except Exception:
            logger.exception("RSS feed fetch failed: %s", source)
            counts["errors"] += 1

    await db.commit()
    return counts
