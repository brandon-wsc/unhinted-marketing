"""Company media storage config + local→S3 migrate (ADR 0025). Editor-only."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.org import require_company_settings_editor
from internal.config import settings
from internal.llm.keys import ByokEncryptionError, encrypt_key, mask_key
from internal.media.config import load_snapshot
from internal.media.migrate import (
    StorageMigrateError,
    clean_migration,
    flip_migration,
    probe_s3,
    rollback_migration,
    run_migration_loop,
    snapshot_from_config,
)
from internal.media.storage import MediaStorageError
from internal.memory import repos
from internal.memory.database import get_db
from internal.memory.models import StorageConfig
from schemas.storage import (
    StorageConfigOut,
    StorageConfigUpdate,
    StorageMigrationOut,
    StorageTestRequest,
    StorageTestResult,
)

router = APIRouter(prefix="/companies/{company_id}/storage", tags=["storage"])


def _http_migrate(exc: StorageMigrateError, code: int = status.HTTP_409_CONFLICT) -> HTTPException:
    return HTTPException(status_code=code, detail=str(exc))


def _s3_row(configs: list[StorageConfig]) -> StorageConfig | None:
    for row in configs:
        if row.backend == "s3":
            return row
    return None


def _local_row(configs: list[StorageConfig]) -> StorageConfig | None:
    for row in configs:
        if row.backend == "local":
            return row
    return None


def _migration_out(row) -> StorageMigrationOut | None:
    if row is None:
        return None
    return StorageMigrationOut.model_validate(row)


async def _config_out(db: AsyncSession) -> StorageConfigOut:
    configs = await repos.list_storage_configs(db)
    active = next((c for c in configs if c.active), None)
    s3 = _s3_row(configs)
    open_m = await repos.get_open_storage_migration(db)
    latest = open_m or await repos.get_latest_storage_migration(db)
    backend = active.backend if active else "local"
    can_migrate = (
        backend == "local"
        and s3 is not None
        and bool((s3.bucket or "").strip())
        and open_m is None
        and settings.deployment_mode != "cloud"
    )
    display = s3 or active
    return StorageConfigOut(
        backend="s3" if backend == "s3" else "local",
        bucket=display.bucket if display else None,
        endpoint_url=display.endpoint_url if display else None,
        region=(display.region if display else None) or "us-east-1",
        public_base_url=display.public_base_url if display else None,
        access_key=display.access_key if display else None,
        secret_last4=display.secret_last4 if display else None,
        seeded_from_env=bool(display.seeded_from_env) if display else False,
        dual_write=open_m is not None,
        can_migrate=can_migrate,
        migration=_migration_out(latest),
    )


def _encrypt_secret(raw: str) -> tuple[str, str]:
    try:
        return encrypt_key(raw), mask_key(raw)
    except ByokEncryptionError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


async def _upsert_s3_target(db: AsyncSession, body: StorageConfigUpdate) -> StorageConfig:
    configs = await repos.list_storage_configs(db)
    s3 = _s3_row(configs)
    if s3 is None:
        enc = last4 = None
        if body.secret_key:
            enc, last4 = _encrypt_secret(body.secret_key)
        s3 = await repos.insert_storage_config(
            db,
            backend="s3",
            bucket=body.bucket,
            endpoint_url=body.endpoint_url,
            region=body.region or "us-east-1",
            public_base_url=body.public_base_url,
            access_key=body.access_key,
            secret_key_encrypted=enc,
            secret_last4=last4,
            active=False,
        )
        if not configs:
            await repos.insert_storage_config(db, backend="local", active=True)
        return s3
    s3.bucket = body.bucket
    s3.endpoint_url = body.endpoint_url
    s3.region = body.region or "us-east-1"
    s3.public_base_url = body.public_base_url
    if body.access_key is not None:
        s3.access_key = body.access_key
    if body.secret_key:
        enc, last4 = _encrypt_secret(body.secret_key)
        s3.secret_key_encrypted = enc
        s3.secret_last4 = last4
    await db.flush()
    return s3


@router.get("/config", response_model=StorageConfigOut)
async def get_storage_config(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StorageConfigOut:
    await load_snapshot(db)
    return await _config_out(db)


@router.put("/config", response_model=StorageConfigOut)
async def put_storage_config(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    body: StorageConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StorageConfigOut:
    open_m = await repos.get_open_storage_migration(db)
    if open_m is not None and open_m.state not in {"completed", "ready_to_flip"}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Cannot change storage settings while a migration is copying.",
        )
    await _upsert_s3_target(db, body)
    await db.commit()
    await load_snapshot(db)
    return await _config_out(db)


@router.post("/test", response_model=StorageTestResult)
async def test_storage_connection(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    body: StorageTestRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StorageTestResult:
    secret = body.secret_key or ""
    if not secret:
        configs = await repos.list_storage_configs(db)
        s3 = _s3_row(configs)
        if s3 and s3.secret_key_encrypted:
            from internal.llm.keys import decrypt_key

            try:
                secret = decrypt_key(s3.secret_key_encrypted)
            except ByokEncryptionError as exc:
                return StorageTestResult(ok=False, error=str(exc))
        elif s3:
            secret = ""
    from internal.media.config import StorageSnapshot

    snap = StorageSnapshot(
        backend="s3",
        bucket=body.bucket,
        endpoint_url=body.endpoint_url or "",
        region=body.region or "us-east-1",
        public_base_url=body.public_base_url or "",
        access_key=body.access_key or "",
        secret_key=secret,
    )
    try:
        probe_s3(snap)
    except MediaStorageError as exc:
        return StorageTestResult(ok=False, error=str(exc)[:400])
    return StorageTestResult(ok=True)


@router.get("/migrations/current", response_model=StorageMigrationOut | None)
async def get_current_migration(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StorageMigrationOut | None:
    row = await repos.get_open_storage_migration(db)
    if row is None:
        row = await repos.get_latest_storage_migration(db)
    return _migration_out(row)


@router.post("/migrations", response_model=StorageMigrationOut, status_code=status.HTTP_201_CREATED)
async def start_migration(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
) -> StorageMigrationOut:
    if settings.deployment_mode == "cloud":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Cloud deployments already use object storage.",
        )
    open_m = await repos.get_open_storage_migration(db)
    if open_m is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A migration is already in progress.")
    configs = await repos.list_storage_configs(db)
    s3 = _s3_row(configs)
    local = _local_row(configs)
    if s3 is None or not (s3.bucket or "").strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Save S3 settings before starting a migration.",
        )
    if local is None:
        local = await repos.insert_storage_config(db, backend="local", active=True)
    active = next((c for c in configs if c.active), local)
    if active.backend != "local":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Active backend is already S3.")
    try:
        probe_s3(snapshot_from_config(s3))
    except (MediaStorageError, StorageMigrateError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    row = await repos.insert_storage_migration(
        db, target_config_id=s3.id, source_config_id=local.id
    )
    await db.commit()
    await load_snapshot(db)
    background_tasks.add_task(run_migration_loop, row.id)
    return StorageMigrationOut.model_validate(row)


@router.post("/migrations/{migration_id}/flip", response_model=StorageMigrationOut)
async def flip_storage_migration(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    migration_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StorageMigrationOut:
    try:
        row = await flip_migration(db, migration_id)
    except StorageMigrateError as exc:
        raise _http_migrate(exc) from exc
    await db.commit()
    await load_snapshot(db)
    return StorageMigrationOut.model_validate(row)


@router.post("/migrations/{migration_id}/rollback", response_model=StorageMigrationOut)
async def rollback_storage_migration(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    migration_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StorageMigrationOut:
    try:
        row = await rollback_migration(db, migration_id)
    except StorageMigrateError as exc:
        raise _http_migrate(exc) from exc
    await db.commit()
    await load_snapshot(db)
    return StorageMigrationOut.model_validate(row)


@router.post("/migrations/{migration_id}/clean", response_model=StorageMigrationOut)
async def clean_storage_migration(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    migration_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StorageMigrationOut:
    try:
        row = await clean_migration(db, migration_id)
    except StorageMigrateError as exc:
        raise _http_migrate(exc) from exc
    await db.commit()
    await load_snapshot(db)
    return StorageMigrationOut.model_validate(row)
