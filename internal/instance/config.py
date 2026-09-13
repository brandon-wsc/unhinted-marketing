"""DB-backed instance settings snapshot (ADR 0026). Env seeds the row only.

Same publish/TTL pattern as ``internal.media.config`` — with one deliberate
difference: ``get_snapshot()`` falls back to env-derived values when the cache
is cold instead of raising, because sync readers run inside SSE emit paths
(media URL resolution, invite links) that cannot await a DB load.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from internal.config import settings
from internal.llm.keys import ByokEncryptionError, decrypt_key
from internal.memory import repos

logger = logging.getLogger(__name__)

TTL_SECONDS = 8.0

EmailBackend = Literal["link", "smtp", "console"]


@dataclass(frozen=True)
class InstanceSnapshot:
    web_base_url: str = ""
    email_backend: EmailBackend = "link"
    email_from: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True


def _strip(value: str | None) -> str:
    return (value or "").strip()


def snapshot_from_env() -> InstanceSnapshot:
    """Env-derived snapshot — seed source and cold-cache fallback."""
    backend = _strip(settings.email_backend).lower()
    return InstanceSnapshot(
        web_base_url=_strip(settings.web_base_url),
        email_backend=backend if backend in ("link", "smtp", "console") else "link",
        email_from=_strip(settings.email_from),
        smtp_host=_strip(settings.smtp_host),
        smtp_port=settings.smtp_port or 587,
        smtp_user=_strip(settings.smtp_user),
        smtp_password=settings.smtp_password or "",
        smtp_tls=settings.smtp_tls,
    )


_cache: InstanceSnapshot | None = None
_cache_at: float = 0.0


def get_snapshot() -> InstanceSnapshot:
    """Last published snapshot, or env fallback when none has been loaded."""
    if _cache is not None:
        return _cache
    return snapshot_from_env()


def publish_snapshot(snapshot: InstanceSnapshot) -> None:
    global _cache, _cache_at
    _cache = snapshot
    _cache_at = time.monotonic()


def cache_is_stale() -> bool:
    if _cache is None:
        return True
    return (time.monotonic() - _cache_at) >= TTL_SECONDS


def reset_snapshot_cache() -> None:
    """Tests: forget any published snapshot so env fallback applies."""
    global _cache, _cache_at
    _cache = None
    _cache_at = 0.0


def _snapshot_from_row(row) -> InstanceSnapshot:
    password = ""
    if row.smtp_password_encrypted:
        try:
            password = decrypt_key(row.smtp_password_encrypted)
        except ByokEncryptionError:
            logger.warning("instance smtp password could not be decrypted")
    backend = _strip(row.email_backend).lower()
    return InstanceSnapshot(
        web_base_url=_strip(row.web_base_url),
        email_backend=backend if backend in ("link", "smtp", "console") else "link",
        email_from=_strip(row.email_from),
        smtp_host=_strip(row.smtp_host),
        smtp_port=row.smtp_port or 587,
        smtp_user=_strip(row.smtp_user),
        smtp_password=password,
        smtp_tls=row.smtp_tls,
    )


async def load_snapshot(db: AsyncSession) -> InstanceSnapshot:
    """Read DB and publish. Call after settings writes and on boot."""
    row = await repos.get_instance_settings(db)
    snap = _snapshot_from_row(row) if row is not None else snapshot_from_env()
    publish_snapshot(snap)
    return snap


async def ensure_instance_settings_seeded(db: AsyncSession) -> None:
    """Insert the singleton row from env when absent (ADR 0026).

    Fresh installs get ``setup_completed_at = NULL`` (wizard pending); the
    migration already back-fills the marker on deployments with users.
    """
    row = await repos.get_instance_settings(db)
    if row is not None:
        await load_snapshot(db)
        return
    env_snap = snapshot_from_env()
    password_enc = None
    last4 = None
    if env_snap.smtp_password:
        from internal.llm.keys import encrypt_key, mask_key

        try:
            password_enc = encrypt_key(env_snap.smtp_password)
            last4 = mask_key(env_snap.smtp_password)
        except ByokEncryptionError:
            logger.warning("could not encrypt seeded SMTP password; storing without it")
    await repos.upsert_instance_settings(
        db,
        web_base_url=env_snap.web_base_url or None,
        email_backend=env_snap.email_backend,
        email_from=env_snap.email_from or None,
        smtp_host=env_snap.smtp_host or None,
        smtp_port=env_snap.smtp_port,
        smtp_user=env_snap.smtp_user or None,
        smtp_password_encrypted=password_enc,
        smtp_password_last4=last4,
        smtp_tls=env_snap.smtp_tls,
    )
    await db.commit()
    await load_snapshot(db)
