"""DB-backed instance settings snapshot (ADR 0026). Env seeds the row only.

Same publish/TTL pattern as ``internal.media.config`` — with one deliberate
difference: ``get_snapshot()`` falls back to env-derived values when the cache
is cold instead of raising, because sync readers (invite links, Instagram
Login callback, Instagram Confirm image fetch, OAuth success landing) cannot
await a DB load.
"""

from __future__ import annotations

import logging
import secrets
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
MetaOAuthMode = Literal["byo", "relay"]


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
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_oauth_mode: MetaOAuthMode = "byo"
    meta_oauth_relay_url: str = ""
    meta_oauth_instance_id: str = ""


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
        meta_app_id=_strip(settings.meta_app_id),
        meta_app_secret=settings.meta_app_secret or "",
        meta_oauth_relay_url=_strip(settings.oauth_relay_url),
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
    meta_secret = ""
    if row.meta_app_secret_encrypted:
        try:
            meta_secret = decrypt_key(row.meta_app_secret_encrypted)
        except ByokEncryptionError:
            logger.warning("instance meta app secret could not be decrypted")
    backend = _strip(row.email_backend).lower()
    meta_mode = _strip(row.meta_oauth_mode).lower()
    return InstanceSnapshot(
        web_base_url=_strip(row.web_base_url),
        email_backend=backend if backend in ("link", "smtp", "console") else "link",
        email_from=_strip(row.email_from),
        smtp_host=_strip(row.smtp_host),
        smtp_port=row.smtp_port or 587,
        smtp_user=_strip(row.smtp_user),
        smtp_password=password,
        smtp_tls=row.smtp_tls,
        meta_app_id=_strip(row.meta_app_id),
        meta_app_secret=meta_secret,
        meta_oauth_mode=meta_mode if meta_mode in ("byo", "relay") else "byo",
        meta_oauth_relay_url=_strip(row.meta_oauth_relay_url),
        meta_oauth_instance_id=_strip(row.meta_oauth_instance_id),
    )


async def load_snapshot(db: AsyncSession) -> InstanceSnapshot:
    """Read DB and publish. Call after settings writes and on boot."""
    row = await repos.get_instance_settings(db)
    snap = _snapshot_from_row(row) if row is not None else snapshot_from_env()
    publish_snapshot(snap)
    return snap


def _encrypt_seed(raw: str, label: str) -> tuple[str | None, str | None]:
    """Encrypt an env secret for seeding; returns (encrypted, last4)."""
    if not raw:
        return None, None
    from internal.llm.keys import encrypt_key, mask_key

    try:
        return encrypt_key(raw), mask_key(raw)
    except ByokEncryptionError:
        logger.warning("could not encrypt seeded %s; storing without it", label)
        return None, None


async def _seed_meta_from_env(db: AsyncSession, env_snap: InstanceSnapshot) -> bool:
    """Backfill Meta app creds when the row never had them (ADR 0032).

    Runs on every boot: ``meta_app_id IS NULL`` means "never set" (a portal
    clear stores ""), so env-configured deployments keep working after the
    upgrade while portal edits still win afterwards.
    """
    row = await repos.get_instance_settings(db)
    if row is None:
        return False
    fields: dict = {}
    if row.meta_app_id is None and env_snap.meta_app_id:
        secret_enc, secret_last4 = _encrypt_seed(
            env_snap.meta_app_secret, "Meta app secret"
        )
        fields["meta_app_id"] = env_snap.meta_app_id
        fields["meta_app_secret_encrypted"] = secret_enc
        fields["meta_app_secret_last4"] = secret_last4
    if row.meta_oauth_relay_url is None and env_snap.meta_oauth_relay_url:
        fields["meta_oauth_relay_url"] = env_snap.meta_oauth_relay_url
    if not row.meta_oauth_instance_id:
        # Registry slug the relay maps to this install's web_base_url.
        fields["meta_oauth_instance_id"] = secrets.token_urlsafe(12)
    if not fields:
        return False
    await repos.upsert_instance_settings(db, **fields)
    await db.commit()
    return True


async def ensure_instance_settings_seeded(db: AsyncSession) -> None:
    """Insert the singleton row from env when absent (ADR 0026).

    Fresh installs get ``setup_completed_at = NULL`` (wizard pending); the
    migration already back-fills the marker on deployments with users.
    """
    env_snap = snapshot_from_env()
    row = await repos.get_instance_settings(db)
    if row is not None:
        await _seed_meta_from_env(db, env_snap)
        await load_snapshot(db)
        return
    password_enc, last4 = _encrypt_seed(env_snap.smtp_password, "SMTP password")
    meta_enc, meta_last4 = _encrypt_seed(env_snap.meta_app_secret, "Meta app secret")
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
        meta_app_id=env_snap.meta_app_id or None,
        meta_app_secret_encrypted=meta_enc,
        meta_app_secret_last4=meta_last4,
        meta_oauth_relay_url=env_snap.meta_oauth_relay_url or None,
        meta_oauth_instance_id=secrets.token_urlsafe(12),
    )
    await db.commit()
    await load_snapshot(db)
