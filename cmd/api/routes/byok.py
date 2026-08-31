"""Org BYOK routes — editor-only keys / models / routing (ADR 0020)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.auth.org import require_company_settings_editor
from internal.auth.rate_limit import enforce_byok_probe_rate_limit
from internal.config import settings
from internal.llm.keys import ByokEncryptionError, encrypt_key, mask_key
from internal.llm.probes import (
    apply_probe_result,
    cached_provider_models,
    invalidate_model_list_cache,
    probe_chat_model_live,
    probe_image_model_live,
    probe_provider_auth,
    run_model_format_probe,
    run_provider_auth_probe,
)
from internal.llm.ssrf import UnsafeUrlError, validate_user_url
from internal.memory.database import get_db
from internal.memory.models import ByokModel, ByokProvider, User
from internal.memory.repos import (
    ROUTING_SLOT_COLUMNS,
    create_byok_model,
    create_byok_provider,
    get_byok_model,
    get_byok_model_by_provider_model,
    get_byok_provider,
    get_byok_routing,
    list_byok_models,
    list_byok_models_by_ids,
    list_byok_models_for_provider,
    list_byok_providers,
    routing_slots_for_model,
    routing_slots_for_models,
    upsert_byok_routing,
)
from schemas.byok import (
    ByokDeleteConflict,
    ByokDependentModel,
    ByokModelCreate,
    ByokModelDeleted,
    ByokModelItem,
    ByokModelList,
    ByokModelListProxy,
    ByokProbeResult,
    ByokProviderCreate,
    ByokProviderDeleted,
    ByokProviderItem,
    ByokProviderList,
    ByokProviderPatch,
    ByokRoutingResponse,
    ByokRoutingSlot,
    ByokRoutingUpdate,
)

router = APIRouter(prefix="/companies/{company_id}/byok", tags=["byok"])

_ENV_MODELS = {
    "cheap": lambda: settings.llm_cheap_model,
    "medium": lambda: settings.llm_medium_model,
    "strong": lambda: settings.llm_strong_model,
    "image": lambda: (settings.llm_image_model or "").strip() or None,
}


def _http_conflict(payload: ByokDeleteConflict) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=payload.model_dump(mode="json"),
    )


def _validate_api_base(api_base: str | None) -> None:
    if not api_base:
        return
    try:
        validate_user_url(api_base)
    except UnsafeUrlError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


def _encrypt_or_503(raw: str) -> str:
    try:
        return encrypt_key(raw)
    except ByokEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def _provider_item(row: ByokProvider) -> ByokProviderItem:
    return ByokProviderItem(
        id=row.id,
        label=row.label,
        provider_type=row.provider_type,  # type: ignore[arg-type]
        key_last4=row.key_last4,
        api_base=row.api_base,
        last_verified_at=row.last_verified_at,
        last_error_kind=row.last_error_kind,
        verified=row.last_verified_at is not None and row.last_error_kind is None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _model_item(row: ByokModel) -> ByokModelItem:
    provider = row.provider
    return ByokModelItem(
        id=row.id,
        provider_id=row.provider_id,
        provider_label=provider.label if provider is not None else "",
        provider_key_last4=provider.key_last4 if provider is not None else "",
        model_id=row.model_id,
        capability=row.capability,  # type: ignore[arg-type]
        capability_source=row.capability_source,  # type: ignore[arg-type]
        last_verified_at=row.last_verified_at,
        last_error_kind=row.last_error_kind,
        verified=row.last_verified_at is not None and row.last_error_kind is None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _require_provider(
    db: AsyncSession, company_id: uuid.UUID, provider_id: uuid.UUID
) -> ByokProvider:
    row = await get_byok_provider(db, company_id, provider_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    return row


async def _require_model(
    db: AsyncSession, company_id: uuid.UUID, model_pk: uuid.UUID
) -> ByokModel:
    row = await get_byok_model(db, company_id, model_pk)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    return row


@router.get("/providers", response_model=ByokProviderList)
async def list_providers(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ByokProviderList:
    rows = await list_byok_providers(db, company_id)
    return ByokProviderList(items=[_provider_item(row) for row in rows])


@router.post("/providers", response_model=ByokProviderItem, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ByokProviderCreate,
    background_tasks: BackgroundTasks,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ByokProviderItem:
    _validate_api_base(body.api_base)
    row = await create_byok_provider(
        db,
        company_id=company_id,
        label=body.label,
        provider_type=body.provider_type,
        api_key_encrypted=_encrypt_or_503(body.api_key),
        key_last4=mask_key(body.api_key),
        api_base=body.api_base,
        created_by=user.id,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provider could not be saved",
        ) from exc
    await db.refresh(row)
    background_tasks.add_task(run_provider_auth_probe, row.id, company_id)
    return _provider_item(row)


@router.patch("/providers/{provider_id}", response_model=ByokProviderItem)
async def patch_provider(
    provider_id: uuid.UUID,
    body: ByokProviderPatch,
    background_tasks: BackgroundTasks,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ByokProviderItem:
    row = await _require_provider(db, company_id, provider_id)
    requeue = False
    if body.label is not None:
        row.label = body.label
    if body.api_key is not None:
        row.api_key_encrypted = _encrypt_or_503(body.api_key)
        row.key_last4 = mask_key(body.api_key)
        row.last_verified_at = None
        row.last_error_kind = None
        requeue = True
    if "api_base" in body.model_fields_set:
        next_base = body.api_base
        if row.provider_type == "openai_compatible" and not next_base:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="api_base is required for openai_compatible",
            )
        _validate_api_base(next_base)
        if next_base != row.api_base:
            row.api_base = next_base
            row.last_verified_at = None
            row.last_error_kind = None
            requeue = True
    row.updated_by = user.id
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provider could not be saved",
        ) from exc
    await db.refresh(row)
    if requeue:
        invalidate_model_list_cache(row.id)
        background_tasks.add_task(run_provider_auth_probe, row.id, company_id)
    return _provider_item(row)


@router.delete("/providers/{provider_id}")
async def delete_provider(
    provider_id: uuid.UUID,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    force: bool = Query(False),
) -> ByokProviderDeleted:
    row = await _require_provider(db, company_id, provider_id)
    models = await list_byok_models_for_provider(db, company_id, provider_id)
    routing = await get_byok_routing(db, company_id)
    model_pks = {m.id for m in models}
    slots = routing_slots_for_models(routing, model_pks)
    if (models or slots) and not force:
        raise _http_conflict(
            ByokDeleteConflict(
                models=[
                    ByokDependentModel(
                        id=m.id,
                        model_id=m.model_id,
                        slots=routing_slots_for_model(routing, m.id),  # type: ignore[arg-type]
                    )
                    for m in models
                ],
                slots=slots,  # type: ignore[arg-type]
            )
        )
    removed = [m.id for m in models]
    await db.delete(row)
    await db.commit()
    invalidate_model_list_cache(provider_id)
    return ByokProviderDeleted(
        id=provider_id, removed_models=removed, cleared_slots=slots  # type: ignore[arg-type]
    )


@router.post("/providers/{provider_id}/test", response_model=ByokProbeResult)
async def test_provider(
    provider_id: uuid.UUID,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ByokProbeResult:
    enforce_byok_probe_rate_limit(user_id=user.id)
    row = await _require_provider(db, company_id, provider_id)
    result = await probe_provider_auth(row)
    apply_probe_result(row, result)
    await db.commit()
    return result


@router.get("/providers/{provider_id}/models", response_model=ByokModelListProxy)
async def list_provider_catalog(
    provider_id: uuid.UUID,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ByokModelListProxy:
    enforce_byok_probe_rate_limit(user_id=user.id)
    row = await _require_provider(db, company_id, provider_id)
    return await cached_provider_models(row)


@router.get("/models", response_model=ByokModelList)
async def list_models(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ByokModelList:
    rows = await list_byok_models(db, company_id)
    return ByokModelList(items=[_model_item(row) for row in rows])


@router.post("/models", response_model=ByokModelItem)
async def create_or_attach_model(
    body: ByokModelCreate,
    background_tasks: BackgroundTasks,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
) -> ByokModelItem:
    provider = await _require_provider(db, company_id, body.provider_id)
    existing = await get_byok_model_by_provider_model(
        db, company_id, provider.id, body.model_id
    )
    if existing is not None:
        existing.capability = body.capability
        existing.capability_source = body.capability_source
        existing.last_verified_at = None
        existing.last_error_kind = None
        await db.commit()
        row = await _require_model(db, company_id, existing.id)
        background_tasks.add_task(run_model_format_probe, row.id, company_id)
        response.status_code = status.HTTP_200_OK
        return _model_item(row)
    await create_byok_model(
        db,
        company_id=company_id,
        provider_id=provider.id,
        model_id=body.model_id,
        capability=body.capability,
        capability_source=body.capability_source,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Model could not be saved",
        ) from exc
    row = await get_byok_model_by_provider_model(db, company_id, provider.id, body.model_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Model save failed")
    background_tasks.add_task(run_model_format_probe, row.id, company_id)
    response.status_code = status.HTTP_201_CREATED
    return _model_item(row)


@router.delete("/models/{model_id}")
async def delete_model(
    model_id: uuid.UUID,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    force: bool = Query(False),
) -> ByokModelDeleted:
    row = await _require_model(db, company_id, model_id)
    routing = await get_byok_routing(db, company_id)
    slots = routing_slots_for_model(routing, row.id)
    if slots and not force:
        raise _http_conflict(ByokDeleteConflict(slots=slots))  # type: ignore[arg-type]
    await db.delete(row)
    await db.commit()
    return ByokModelDeleted(id=model_id, cleared_slots=slots)  # type: ignore[arg-type]


@router.post("/models/{model_id}/test", response_model=ByokProbeResult)
async def test_model(
    model_id: uuid.UUID,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    confirm_paid: bool = Query(False),
) -> ByokProbeResult:
    enforce_byok_probe_rate_limit(user_id=user.id)
    row = await _require_model(db, company_id, model_id)
    if row.provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    if row.capability == "image":
        if not confirm_paid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image tests call a paid image API. Pass confirm_paid=true.",
            )
        result = await probe_image_model_live(row.provider, row.model_id)
    else:
        result = await probe_chat_model_live(row.provider, row.model_id)
    apply_probe_result(row, result)
    await db.commit()
    return result


@router.get("/routing", response_model=ByokRoutingResponse)
async def get_routing(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ByokRoutingResponse:
    routing = await get_byok_routing(db, company_id)
    ids = [
        getattr(routing, column)
        for _, column in ROUTING_SLOT_COLUMNS
        if routing is not None and getattr(routing, column) is not None
    ]
    models = await list_byok_models_by_ids(db, company_id, ids)
    by_id = {m.id: m for m in models}
    slots: list[ByokRoutingSlot] = []
    for slot, column in ROUTING_SLOT_COLUMNS:
        expected = "image" if slot == "image" else "chat"
        registry_id = getattr(routing, column) if routing is not None else None
        model = by_id.get(registry_id) if registry_id else None
        if model is not None and (model.capability or "").strip() == expected:
            slots.append(
                ByokRoutingSlot(
                    slot=slot,  # type: ignore[arg-type]
                    source="org",
                    registry_id=model.id,
                    model_id=model.model_id,
                )
            )
            continue
        env_id = _ENV_MODELS[slot]()
        slots.append(
            ByokRoutingSlot(
                slot=slot,  # type: ignore[arg-type]
                source="env",
                registry_id=None,
                model_id=env_id,
            )
        )
    return ByokRoutingResponse(slots=slots)


@router.put("/routing", response_model=ByokRoutingResponse)
async def put_routing(
    body: ByokRoutingUpdate,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ByokRoutingResponse:
    wanted = {
        "cheap": body.cheap_model_id,
        "medium": body.medium_model_id,
        "strong": body.strong_model_id,
        "image": body.image_model_id,
    }
    ids = [mid for mid in wanted.values() if mid is not None]
    models = await list_byok_models_by_ids(db, company_id, ids)
    by_id = {m.id: m for m in models}
    for slot, mid in wanted.items():
        if mid is None:
            continue
        model = by_id.get(mid)
        if model is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Model not found for slot {slot}",
            )
        expected = "image" if slot == "image" else "chat"
        if (model.capability or "").strip() != expected:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Slot {slot} requires a {expected} model",
            )
    try:
        await upsert_byok_routing(
            db,
            company_id,
            cheap_model_id=body.cheap_model_id,
            medium_model_id=body.medium_model_id,
            strong_model_id=body.strong_model_id,
            image_model_id=body.image_model_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Routing could not be saved",
        ) from exc
    return await get_routing(company_id, db)
