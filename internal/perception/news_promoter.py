"""Promote high-velocity HK signals to topic entities in PostgreSQL."""

import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from internal.config import settings
from internal.memory.repos import (
    create_edge,
    get_or_create_topic_entity,
    list_top_signals,
    signal_has_promotion_edge,
)

logger = logging.getLogger(__name__)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value.lower()).strip("-")
    return slug[:80] or "topic"


def _should_promote(signal) -> bool:
    if signal.source != "google_trends_hk":
        return False
    metrics = signal.metrics or {}
    rank = metrics.get("rank")
    return rank is not None and rank <= settings.news_promote_trends_rank_max


async def promote_signals(db: AsyncSession) -> dict[str, int]:
    since = datetime.now(UTC) - timedelta(hours=settings.news_promote_window_hours)
    signals = await list_top_signals(db, limit=50, region="HK", since=since)
    counts = {"promoted": 0, "skipped": 0}

    for signal in signals:
        if not _should_promote(signal):
            counts["skipped"] += 1
            continue
        if await signal_has_promotion_edge(db, signal.signal_id):
            counts["skipped"] += 1
            continue

        slug = _slugify(signal.title)
        promoted_at = datetime.now(UTC).isoformat()
        profile = {
            "signal_id": signal.signal_id,
            "source": signal.source,
            "region": signal.region,
            "excerpt": signal.excerpt,
            "url": signal.url,
            "metrics": signal.metrics or {},
            "promoted_at": promoted_at,
        }
        topic_entity = await get_or_create_topic_entity(
            db, slug=f"topic-{slug}", name=signal.title, profile=profile
        )
        await create_edge(
            db,
            edge_type="AFFECTS",
            source_signal_id=signal.signal_id,
            from_entity_id=topic_entity.id,
            metadata={"promoted_at": promoted_at},
        )
        counts["promoted"] += 1
        logger.info("Promoted signal %s → topic entity %s", signal.signal_id, topic_entity.slug)

    await db.commit()
    return counts
