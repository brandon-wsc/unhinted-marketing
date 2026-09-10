"""DB-backed media storage snapshot (ADR 0025). Env is seed-only / test fallback."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from internal.config import settings
from internal.llm.keys import ByokEncryptionError, decrypt_key
from internal.memory import repos

logger = logging.getLogger(__name__)

TTL_SECONDS = 8.0

Backend = Literal["local", "s3"]


@dataclass(frozen=True)
class StorageSnapshot:
    backend: Backend
    bucket: str = ""
    endpoint_url: str = ""
    region: str = "us-east-1"
    public_base_url: str = ""
    access_key: str = ""
    secret_key: str = ""
    dual_write: bool = False
    config_id: UUID | None = None
    # Target S3 credentials used during dual-write while active backend is still local.
    dual_bucket: str = ""
    dual_endpoint_url: str = ""
    dual_region: str = ""
    dual_public_base_url: str = ""
    dual_access_key: str = ""
    dual_secret_key: str = ""

    @property
    def fingerprint(self) -> tuple[str, ...]:
        return (
            self.backend,
            self.bucket,
            self.endpoint_url,
            self.region,
            self.access_key,
            self.secret_key,
            self.dual_bucket,
            self.dual_endpoint_url,
        )

    def dual_s3(self) -> StorageSnapshot:
        """Snapshot pointing at the migrate target (S3) for dual-write / copy.

        After flip the active snapshot *is* S3; dual_* fields still describe
        that same bucket. Before flip they come from the inactive target row.
        """
        if self.dual_bucket:
            return StorageSnapshot(
                backend="s3",
                bucket=self.dual_bucket,
                endpoint_url=self.dual_endpoint_url,
                region=self.dual_region or self.region or "us-east-1",
                public_base_url=self.dual_public_base_url,
                access_key=self.dual_access_key,
                secret_key=self.dual_secret_key,
            )
        if self.backend == "s3" and self.bucket:
            return self
        return self


_cache: StorageSnapshot | None = None
_cache_at: float = 0.0


def _strip(value: str | None) -> str:
    return (value or "").strip()


def snapshot_from_env() -> StorageSnapshot:
    """Derive a snapshot from process env (tests + pre-seed fallback)."""
    mode = settings.deployment_mode
    bucket = _strip(settings.s3_bucket)
    endpoint = _strip(settings.s3_endpoint_url)
    access = _strip(settings.s3_access_key)
    secret = _strip(settings.s3_secret_key)
    region = _strip(settings.s3_region) or "us-east-1"
    public = _strip(settings.s3_public_base_url)

    if bool(access) != bool(secret):
        # Incomplete keys are ignored (ADR 0025: env is seed-only, not a hard start check).
        access, secret = "", ""

    if mode == "cloud":
        if not bucket:
            raise RuntimeError("S3_BUCKET is required when DEPLOYMENT_MODE=cloud.")
        return StorageSnapshot(
            backend="s3",
            bucket=bucket,
            endpoint_url=endpoint,
            region=region,
            public_base_url=public,
            access_key=access,
            secret_key=secret,
        )

    if bucket and endpoint:
        return StorageSnapshot(
            backend="s3",
            bucket=bucket,
            endpoint_url=endpoint,
            region=region,
            public_base_url=public,
            access_key=access,
            secret_key=secret,
        )
    return StorageSnapshot(backend="local", region=region)


def get_snapshot() -> StorageSnapshot:
    """Last published snapshot, or env fallback when none has been loaded."""
    if _cache is not None:
        return _cache
    return snapshot_from_env()


def publish_snapshot(snapshot: StorageSnapshot) -> None:
    global _cache, _cache_at
    _cache = snapshot
    _cache_at = time.monotonic()


def invalidate_snapshot() -> None:
    """Drop TTL so the next load replaces the cache. Keep serving the last snapshot."""
    global _cache_at
    _cache_at = 0.0


def cache_is_stale() -> bool:
    if _cache is None:
        return True
    return (time.monotonic() - _cache_at) >= TTL_SECONDS


def reset_snapshot_cache() -> None:
    """Tests: forget any published snapshot so env fallback applies."""
    global _cache, _cache_at
    _cache = None
    _cache_at = 0.0


def _snapshot_from_row(row, *, dual_write: bool, dual_target=None) -> StorageSnapshot:
    secret = ""
    if row.secret_key_encrypted:
        try:
            secret = decrypt_key(row.secret_key_encrypted)
        except ByokEncryptionError:
            logger.warning("storage config secret could not be decrypted")
    dual_secret = ""
    dual_bucket = dual_endpoint = dual_region = dual_public = dual_access = ""
    if dual_target is not None and dual_target.id != row.id:
        if dual_target.secret_key_encrypted:
            try:
                dual_secret = decrypt_key(dual_target.secret_key_encrypted)
            except ByokEncryptionError:
                logger.warning("storage target secret could not be decrypted")
        dual_bucket = _strip(dual_target.bucket)
        dual_endpoint = _strip(dual_target.endpoint_url)
        dual_region = _strip(dual_target.region) or "us-east-1"
        dual_public = _strip(dual_target.public_base_url)
        dual_access = _strip(dual_target.access_key)
    return StorageSnapshot(
        backend="s3" if row.backend == "s3" else "local",
        bucket=_strip(row.bucket),
        endpoint_url=_strip(row.endpoint_url),
        region=_strip(row.region) or "us-east-1",
        public_base_url=_strip(row.public_base_url),
        access_key=_strip(row.access_key),
        secret_key=secret,
        dual_write=dual_write,
        config_id=row.id,
        dual_bucket=dual_bucket,
        dual_endpoint_url=dual_endpoint,
        dual_region=dual_region,
        dual_public_base_url=dual_public,
        dual_access_key=dual_access,
        dual_secret_key=dual_secret,
    )


async def load_snapshot(db: AsyncSession) -> StorageSnapshot:
    """Read DB and publish. Call after config/migration writes and on boot."""
    active = await repos.get_active_storage_config(db)
    open_m = await repos.get_open_storage_migration(db)
    dual = open_m is not None
    dual_target = None
    if open_m and open_m.target_config_id:
        dual_target = await repos.get_storage_config(db, open_m.target_config_id)
    if active is None:
        try:
            snap = replace(snapshot_from_env(), dual_write=dual)
        except RuntimeError:
            snap = StorageSnapshot(backend="local", dual_write=dual)
        if dual_target is not None:
            dual_secret = ""
            if dual_target.secret_key_encrypted:
                try:
                    dual_secret = decrypt_key(dual_target.secret_key_encrypted)
                except ByokEncryptionError:
                    logger.warning("storage target secret could not be decrypted")
            snap = replace(
                snap,
                dual_write=True,
                dual_bucket=_strip(dual_target.bucket),
                dual_endpoint_url=_strip(dual_target.endpoint_url),
                dual_region=_strip(dual_target.region) or "us-east-1",
                dual_public_base_url=_strip(dual_target.public_base_url),
                dual_access_key=_strip(dual_target.access_key),
                dual_secret_key=dual_secret,
            )
    else:
        snap = _snapshot_from_row(active, dual_write=dual, dual_target=dual_target)
    publish_snapshot(snap)
    return snap


async def ensure_storage_config_seeded(db: AsyncSession) -> None:
    """Insert the first row from env when the table is empty (ADR 0025)."""
    existing = await repos.list_storage_configs(db)
    if existing:
        await load_snapshot(db)
        return
    try:
        env_snap = snapshot_from_env()
    except RuntimeError:
        # Cloud without bucket: leave empty; portal / first-use will fail clearly.
        publish_snapshot(StorageSnapshot(backend="local"))
        return
    secret_enc = None
    last4 = None
    if env_snap.secret_key:
        from internal.llm.keys import encrypt_key, mask_key

        try:
            secret_enc = encrypt_key(env_snap.secret_key)
            last4 = mask_key(env_snap.secret_key)
        except ByokEncryptionError:
            logger.warning("could not encrypt seeded S3 secret; storing without it")
    await repos.insert_storage_config(
        db,
        backend=env_snap.backend,
        bucket=env_snap.bucket or None,
        endpoint_url=env_snap.endpoint_url or None,
        region=env_snap.region,
        public_base_url=env_snap.public_base_url or None,
        access_key=env_snap.access_key or None,
        secret_key_encrypted=secret_enc,
        secret_last4=last4,
        seeded_from_env=True,
        active=True,
    )
    await db.commit()
    await load_snapshot(db)
