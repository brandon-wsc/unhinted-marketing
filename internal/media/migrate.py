"""Leased local→S3 media migration (ADR 0025)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from internal.config import settings
from internal.media.config import StorageSnapshot, load_snapshot
from internal.media.storage import (
    MediaStorageError,
    _head_s3_size_sync,
    _put_s3_sync,
    extract_store_key,
    local_abs_path,
    s3_client_for,
)
from internal.memory import repos
from internal.memory.database import open_session
from internal.memory.models import StorageConfig, StorageMigration

logger = logging.getLogger(__name__)

LEASE_SECONDS = 30
BATCH_SIZE = 200
PROBE_PREFIX = ".unhinted-probe/"
_running: set[uuid.UUID] = set()
_tasks: set[asyncio.Task] = set()


class StorageMigrateError(Exception):
    """Validation or state-machine failure visible to the portal."""


def _now() -> datetime:
    return datetime.now(UTC)


def _lease_until() -> datetime:
    return _now() + timedelta(seconds=LEASE_SECONDS)


def _stats(row: StorageMigration) -> dict:
    base = {"scanned": 0, "copied": 0, "skipped": 0, "bytes": 0, "orphans": 0}
    if isinstance(row.stats, dict):
        base.update(row.stats)
    return base


def enumerate_store_keys(refs: list[str]) -> list[str]:
    keys: set[str] = set()
    for ref in refs:
        key = extract_store_key(ref)
        if key:
            keys.add(key)
    return sorted(keys)


def count_orphan_files(known: set[str]) -> int:
    root = Path(settings.media_root).expanduser().resolve()
    if not root.is_dir():
        return 0
    orphans = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.endswith(".tmp"):
            continue
        if rel not in known:
            orphans += 1
    return orphans


def snapshot_from_config(row: StorageConfig) -> StorageSnapshot:
    from internal.llm.keys import ByokEncryptionError, decrypt_key

    secret = ""
    if row.secret_key_encrypted:
        try:
            secret = decrypt_key(row.secret_key_encrypted)
        except ByokEncryptionError as exc:
            raise StorageMigrateError(str(exc)) from exc
    return StorageSnapshot(
        backend="s3",
        bucket=(row.bucket or "").strip(),
        endpoint_url=(row.endpoint_url or "").strip(),
        region=(row.region or "us-east-1").strip() or "us-east-1",
        public_base_url=(row.public_base_url or "").strip(),
        access_key=(row.access_key or "").strip(),
        secret_key=secret,
    )


def probe_s3(snap: StorageSnapshot) -> None:
    """Put + head + delete a probe object. Raises MediaStorageError on failure."""
    if not snap.bucket:
        raise MediaStorageError("S3 bucket is required.")
    key = f"{PROBE_PREFIX}{uuid.uuid4().hex}.txt"
    body = b"unhinted-storage-probe"
    try:
        _put_s3_sync(snap=snap, key=key, data=body, content_type="text/plain")
        size = _head_s3_size_sync(snap=snap, key=key)
    except MediaStorageError:
        raise
    except Exception as exc:
        raise MediaStorageError(str(exc)) from exc
    try:
        s3_client_for(snap).delete_object(Bucket=snap.bucket, Key=key)
    except Exception:
        logger.warning("probe cleanup failed for key=%s", key, exc_info=True)
    if size != len(body):
        raise MediaStorageError("S3 probe head_object size mismatch.")


async def _require_target(db: AsyncSession, row: StorageMigration) -> StorageConfig:
    if not row.target_config_id:
        raise StorageMigrateError("Migration has no target config.")
    target = await repos.get_storage_config(db, row.target_config_id)
    if target is None or target.backend != "s3" or not (target.bucket or "").strip():
        raise StorageMigrateError("Target S3 config is missing or incomplete.")
    return target


async def _copy_one(snap: StorageSnapshot, key: str) -> tuple[str, int]:
    """Return ('copied'|'skipped'|'missing', size)."""
    path = local_abs_path(key)
    if not path.is_file():
        return "missing", 0
    data = path.read_bytes()
    existing = await asyncio.to_thread(_head_s3_size_sync, snap=snap, key=key)
    if existing == len(data):
        return "skipped", len(data)
    await asyncio.to_thread(
        _put_s3_sync, snap=snap, key=key, data=data, content_type="application/octet-stream"
    )
    size = await asyncio.to_thread(_head_s3_size_sync, snap=snap, key=key)
    if size != len(data):
        raise MediaStorageError(f"size mismatch after put for {key}")
    return "copied", len(data)


async def _run_copy_pass(
    db: AsyncSession,
    row: StorageMigration,
    snap: StorageSnapshot,
    keys: list[str],
    *,
    verifying: bool,
) -> None:
    stats = _stats(row)
    errors: list = list(row.error_keys or [])
    cursor = row.cursor
    pending = [k for k in keys if cursor is None or k > cursor]
    if verifying:
        pending = keys
        cursor = None
    stats["scanned"] = len(keys)
    i = 0
    while i < len(pending):
        batch = pending[i : i + BATCH_SIZE]
        for key in batch:
            if await repos.is_migration_key_done(db, key):
                stats["skipped"] = int(stats.get("skipped", 0)) + 1
                cursor = key
                continue
            try:
                status, size = await _copy_one(snap, key)
            except Exception as exc:
                logger.warning("copy failed key=%s", key, exc_info=True)
                errors.append({"key": key, "error": str(exc)[:300]})
                cursor = key
                continue
            if status == "missing":
                errors.append({"key": key, "error": "local file missing"})
            else:
                await repos.mark_migration_key_done(db, key, size)
                if status == "copied":
                    stats["copied"] = int(stats.get("copied", 0)) + 1
                    stats["bytes"] = int(stats.get("bytes", 0)) + size
                else:
                    stats["skipped"] = int(stats.get("skipped", 0)) + 1
            cursor = key
        row.cursor = cursor
        row.stats = stats
        row.error_keys = errors[-50:]
        await repos.renew_storage_migration_lease(db, row.id, lease_until=_lease_until())
        await db.commit()
        i += BATCH_SIZE


async def run_migration_loop(migration_id: uuid.UUID) -> None:
    """Claim the lease and advance validating → copying → verifying → ready_to_flip."""
    if migration_id in _running:
        return
    _running.add(migration_id)
    backoff = 1.0
    try:
        async with open_session() as db:
            claimed = await repos.claim_storage_migration_lease(
                db, migration_id, lease_until=_lease_until()
            )
            if claimed is None:
                return
            await db.commit()
            while True:
                row = await repos.get_storage_migration(db, migration_id)
                if row is None:
                    return
                if row.state in {
                    "ready_to_flip",
                    "flipping",
                    "completed",
                    "cleaning",
                    "done",
                    "failed",
                }:
                    return
                try:
                    target = await _require_target(db, row)
                    snap = snapshot_from_config(target)
                    if row.state == "validating":
                        await asyncio.to_thread(probe_s3, snap)
                        refs = await repos.list_all_media_refs(db)
                        keys = enumerate_store_keys(refs)
                        row.stats = {
                            **_stats(row),
                            "scanned": len(keys),
                            "orphans": count_orphan_files(set(keys)),
                        }
                        row.state = "copying"
                        row.error = None
                        await repos.renew_storage_migration_lease(
                            db, row.id, lease_until=_lease_until()
                        )
                        await db.commit()
                        continue
                    refs = await repos.list_all_media_refs(db)
                    keys = enumerate_store_keys(refs)
                    if row.state == "copying":
                        await _run_copy_pass(db, row, snap, keys, verifying=False)
                        row = await repos.get_storage_migration(db, migration_id)
                        assert row is not None
                        row.state = "verifying"
                        row.cursor = None
                        await db.commit()
                        continue
                    if row.state == "verifying":
                        await _run_copy_pass(db, row, snap, keys, verifying=True)
                        row = await repos.get_storage_migration(db, migration_id)
                        assert row is not None
                        done = set(await repos.list_done_migration_keys(db))
                        missing = [k for k in keys if k not in done]
                        local_missing = {
                            e["key"]
                            for e in (row.error_keys or [])
                            if isinstance(e, dict)
                            and e.get("error") == "local file missing"
                        }
                        still = [k for k in missing if k not in local_missing]
                        if still:
                            row.error = f"{len(still)} keys still missing on target"
                            await db.commit()
                            await asyncio.sleep(min(30.0, backoff))
                            backoff = min(30.0, backoff * 2)
                            continue
                        row.state = "ready_to_flip"
                        row.error = None
                        await db.commit()
                        await load_snapshot(db)
                        return
                except Exception as exc:
                    logger.exception("migration %s failed", migration_id)
                    row = await repos.get_storage_migration(db, migration_id)
                    if row is not None:
                        row.state = "failed"
                        row.error = str(exc)[:1000]
                        await db.commit()
                    return
    finally:
        _running.discard(migration_id)


def kick_migration(migration_id: uuid.UUID) -> None:
    """Schedule the lease loop on the running event loop (API process)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(run_migration_loop(migration_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def resume_open_migration() -> None:
    """Boot: continue a copy that was in flight when the process died."""
    async with open_session() as db:
        row = await repos.get_open_storage_migration(db)
        if row is None:
            return
        if row.state in {"validating", "copying", "verifying"}:
            kick_migration(row.id)


async def flip_migration(db: AsyncSession, migration_id: uuid.UUID) -> StorageMigration:
    row = await repos.get_storage_migration(db, migration_id)
    if row is None:
        raise StorageMigrateError("Migration not found.")
    if row.state not in {"ready_to_flip", "completed"}:
        raise StorageMigrateError("Migration is not ready to flip.")
    target = await _require_target(db, row)
    await repos.deactivate_storage_configs(db)
    target.active = True
    row.state = "completed"
    row.error = None
    await db.flush()
    await load_snapshot(db)
    return row


async def rollback_migration(db: AsyncSession, migration_id: uuid.UUID) -> StorageMigration:
    row = await repos.get_storage_migration(db, migration_id)
    if row is None:
        raise StorageMigrateError("Migration not found.")
    if row.state not in {"completed", "ready_to_flip"}:
        raise StorageMigrateError("Rollback is only available until local cleanup.")
    source = None
    if row.source_config_id:
        source = await repos.get_storage_config(db, row.source_config_id)
    if source is None:
        raise StorageMigrateError("Source local config is missing.")
    await repos.deactivate_storage_configs(db)
    source.active = True
    row.state = "ready_to_flip"
    await db.flush()
    await load_snapshot(db)
    return row


async def clean_migration(db: AsyncSession, migration_id: uuid.UUID) -> StorageMigration:
    row = await repos.get_storage_migration(db, migration_id)
    if row is None:
        raise StorageMigrateError("Migration not found.")
    if row.state != "completed":
        raise StorageMigrateError("Cleanup is only available after a successful flip.")
    active = await repos.get_active_storage_config(db)
    if active is None or active.backend != "s3":
        raise StorageMigrateError("Active backend must be S3 before cleaning local files.")
    row.state = "cleaning"
    await db.flush()
    await db.commit()
    keys = await repos.list_done_migration_keys(db)
    for key in keys:
        try:
            path = local_abs_path(key)
            path.unlink(missing_ok=True)
        except MediaStorageError:
            continue
    await repos.clear_migration_done_keys(db)
    row = await repos.get_storage_migration(db, migration_id)
    assert row is not None
    row.state = "done"
    await db.flush()
    await db.refresh(row)
    await load_snapshot(db)
    return row
