"""Admin read APIs (ADR 0005) — gated by platform level, never tenant RBAC."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.roles import PlatformLevel, require_platform_level
from internal.memory.database import get_db
from internal.memory.models import LlmCallRecord, User
from schemas.admin import LlmCallRecordDetail, LlmCallRecordList, LlmCallRecordSummary

router = APIRouter(prefix="/admin", tags=["admin"])

AdminUser = Annotated[User, Depends(require_platform_level(PlatformLevel.ADMIN))]


@router.get("/llm-calls", response_model=LlmCallRecordList)
async def list_llm_calls(
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    node: Annotated[str | None, Query(max_length=60)] = None,
    caller: Annotated[str | None, Query(max_length=80)] = None,
    kind: Annotated[str | None, Query(max_length=20)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=20)] = None,
    session_id: uuid.UUID | None = None,
    fallback_used: bool | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LlmCallRecordList:
    stmt = select(LlmCallRecord)
    if node:
        stmt = stmt.where(LlmCallRecord.node == node)
    if caller:
        stmt = stmt.where(LlmCallRecord.caller == caller)
    if kind:
        stmt = stmt.where(LlmCallRecord.kind == kind)
    if status_filter:
        stmt = stmt.where(LlmCallRecord.status == status_filter)
    if session_id:
        stmt = stmt.where(LlmCallRecord.session_id == session_id)
    if fallback_used is not None:
        stmt = stmt.where(LlmCallRecord.fallback_used == fallback_used)
    if since:
        stmt = stmt.where(LlmCallRecord.created_at >= since)
    if until:
        stmt = stmt.where(LlmCallRecord.created_at <= until)
    stmt = stmt.order_by(desc(LlmCallRecord.created_at)).limit(limit).offset(offset)

    rows = (await db.scalars(stmt)).all()
    return LlmCallRecordList(
        items=[LlmCallRecordSummary.model_validate(row) for row in rows],
        limit=limit,
        offset=offset,
    )


@router.get("/llm-calls/{record_id}", response_model=LlmCallRecordDetail)
async def get_llm_call(
    record_id: uuid.UUID,
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LlmCallRecordDetail:
    row = await db.get(LlmCallRecord, record_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    return LlmCallRecordDetail.model_validate(row)
