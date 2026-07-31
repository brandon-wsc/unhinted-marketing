"""Ingest HK hot search signals from Google Trends."""

import hashlib
import logging
import re
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory.repos import upsert_signal

logger = logging.getLogger(__name__)

SOURCE_TRENDS = "google_trends_hk"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or "signal"


def _signal_id(source: str, key: str) -> str:
    digest = hashlib.sha256(f"{source}:{key}".encode()).hexdigest()[:16]
    return f"{source}:{digest}"


async def fetch_google_trends_hk() -> list[dict]:
    try:
        from pytrends.request import TrendReq
    except ImportError as exc:
        raise RuntimeError("pytrends is not installed") from exc

    pytrends = TrendReq(hl="zh-HK", tz=480, timeout=(10, 25))
    titles: list[str] = []

    for fetch in (
        lambda: pytrends.trending_searches(pn="hong_kong"),
        lambda: pytrends.realtime_trending_searches(pn="HK"),
    ):
        try:
            df = fetch()
            if df is not None and not df.empty:
                col = df.columns[0] if len(df.columns) else 0
                titles = [str(v).strip() for v in df[col].tolist() if str(v).strip()]
                if titles:
                    break
        except Exception:
            logger.debug("Trend fetch attempt failed", exc_info=True)

    if not titles:
        raise RuntimeError("All Google Trends HK fetch methods failed")

    items: list[dict] = []
    for rank, title in enumerate(titles, start=1):
        slug = _slugify(title)
        items.append(
            {
                "signal_id": _signal_id(SOURCE_TRENDS, slug),
                "source": SOURCE_TRENDS,
                "title": title,
                "url": None,
                "excerpt": f"Google Trends HK rank #{rank}",
                "metrics": {"rank": rank, "keyword": title},
            }
        )
    return items


async def ingest_hot_search(db: AsyncSession) -> dict[str, int]:
    """Fetch Google Trends HK and upsert into raw_news_events."""
    counts = {"google_trends_hk": 0, "errors": 0}
    now = datetime.now(UTC)

    try:
        items = await fetch_google_trends_hk()
        for item in items:
            await upsert_signal(
                db,
                signal_id=item["signal_id"],
                source=item["source"],
                title=item["title"],
                url=item.get("url"),
                excerpt=item.get("excerpt"),
                metrics=item.get("metrics") or {},
                ingested_at=now,
            )
            counts["google_trends_hk"] += 1
    except Exception:
        logger.exception("Google Trends HK fetch failed")
        counts["errors"] += 1

    await db.commit()
    return counts
