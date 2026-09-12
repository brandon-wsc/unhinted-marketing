"""Eager media GC on session delete (ADR 0024). Object delete runs after DB commit."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from internal.media.storage import delete_key, extract_store_key
from internal.memory import repos

logger = logging.getLogger(__name__)


async def collect_session_store_keys(db: AsyncSession, session_id: uuid.UUID) -> list[str]:
    """Peel store keys from this session's preview rows (legacy baked URLs included)."""
    keys: list[str] = []
    seen: set[str] = set()
    for ref in await repos.list_session_media_refs(db, session_id):
        key = extract_store_key(ref)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


async def reclaim_unreferenced_keys(db: AsyncSession, keys: list[str]) -> None:
    """Delete keys with zero remaining preview refs. Failures log and never raise."""
    for key in keys:
        try:
            refs = await repos.list_matching_media_refs(db, key)
            if any(extract_store_key(u) == key for u in refs):
                continue
            await delete_key(key)
        except Exception:
            logger.warning("media GC failed for key=%s", key, exc_info=True)
