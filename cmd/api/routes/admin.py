"""Admin read APIs (ADR 0005 / Trace viewer) — gated by platform level, never tenant RBAC."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.roles import PlatformLevel, require_platform_level
from internal.memory import repos
from internal.memory.database import get_db
from internal.memory.models import (
    LlmCallRecord,
    PreviewDraft,
    Session,
    SessionMessage,
    SessionNodeStep,
    User,
)
from schemas.admin import (
    LlmCallRecordDetail,
    LlmCallRecordList,
    LlmCallRecordSummary,
    NodeStepDetail,
    NodeStepList,
    NodeStepSummary,
    SessionTrace,
    TraceDraftRevision,
    TraceMessage,
    TraceSignal,
    TraceTurn,
)

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
    turn_id: uuid.UUID | None = None,
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
    if turn_id:
        stmt = stmt.where(LlmCallRecord.turn_id == turn_id)
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


@router.get("/node-steps", response_model=NodeStepList)
async def list_node_steps(
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    node: Annotated[str | None, Query(max_length=60)] = None,
    session_id: uuid.UUID | None = None,
    turn_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NodeStepList:
    stmt = select(SessionNodeStep)
    if node:
        stmt = stmt.where(SessionNodeStep.node == node)
    if session_id:
        stmt = stmt.where(SessionNodeStep.session_id == session_id)
    if turn_id:
        stmt = stmt.where(SessionNodeStep.turn_id == turn_id)
    if since:
        stmt = stmt.where(SessionNodeStep.created_at >= since)
    if until:
        stmt = stmt.where(SessionNodeStep.created_at <= until)
    stmt = (
        stmt.order_by(desc(SessionNodeStep.created_at), asc(SessionNodeStep.seq))
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.scalars(stmt)).all()
    return NodeStepList(
        items=[NodeStepSummary.model_validate(row) for row in rows],
        limit=limit,
        offset=offset,
    )


@router.get("/node-steps/{step_id}", response_model=NodeStepDetail)
async def get_node_step(
    step_id: uuid.UUID,
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NodeStepDetail:
    row = await db.get(SessionNodeStep, step_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Step not found")
    llm_rows = (
        await db.scalars(
            select(LlmCallRecord)
            .where(
                LlmCallRecord.turn_id == row.turn_id,
                LlmCallRecord.node == row.node,
            )
            .order_by(asc(LlmCallRecord.created_at))
        )
    ).all()
    detail = NodeStepDetail.model_validate(row)
    detail.llm_calls = [LlmCallRecordSummary.model_validate(r) for r in llm_rows]
    return detail


@router.get("/sessions/{session_id}/trace", response_model=SessionTrace)
async def get_session_trace(
    session_id: uuid.UUID,
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionTrace:
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    messages = (
        await db.scalars(
            select(SessionMessage)
            .where(SessionMessage.session_id == session_id)
            .order_by(asc(SessionMessage.created_at))
        )
    ).all()
    drafts = (
        await db.scalars(
            select(PreviewDraft)
            .where(PreviewDraft.session_id == session_id)
            .order_by(asc(PreviewDraft.revision))
        )
    ).all()
    steps = (
        await db.scalars(
            select(SessionNodeStep)
            .where(SessionNodeStep.session_id == session_id)
            .order_by(asc(SessionNodeStep.created_at), asc(SessionNodeStep.seq))
        )
    ).all()
    llm_calls = (
        await db.scalars(
            select(LlmCallRecord)
            .where(LlmCallRecord.session_id == session_id)
            .order_by(asc(LlmCallRecord.created_at))
        )
    ).all()

    signal_ids: list[str] = []
    seen: set[str] = set()
    for draft in drafts:
        for sid in draft.source_signal_ids or []:
            key = str(sid)
            if key not in seen:
                seen.add(key)
                signal_ids.append(key)
    for step in steps:
        for sid in list(step.source_signal_ids_in or []) + list(step.source_signal_ids_out or []):
            key = str(sid)
            if key not in seen:
                seen.add(key)
                signal_ids.append(key)

    signal_rows = await repos.get_signals_by_ids(db, signal_ids)

    turns_map: dict[uuid.UUID, TraceTurn] = {}
    turn_order: list[uuid.UUID] = []

    def _ensure_turn(tid: uuid.UUID) -> TraceTurn:
        if tid not in turns_map:
            turns_map[tid] = TraceTurn(turn_id=tid)
            turn_order.append(tid)
        return turns_map[tid]

    for step in steps:
        _ensure_turn(step.turn_id).steps.append(NodeStepSummary.model_validate(step))
    for call in llm_calls:
        if call.turn_id is None:
            continue
        _ensure_turn(call.turn_id).llm_calls.append(LlmCallRecordSummary.model_validate(call))

    return SessionTrace(
        id=session.id,
        mode=session.mode,
        status=session.status,
        company_id=session.company_id,
        user_id=session.user_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[
            TraceMessage(
                id=m.id,
                role=m.role,
                content=m.content,
                metadata=m.metadata_ or None,
                created_at=m.created_at,
            )
            for m in messages
        ],
        draft_revisions=[
            TraceDraftRevision(
                id=d.id,
                revision=d.revision,
                draft_copy=d.copy or {},
                image_url=d.image_url,
                image_plan=d.image_plan,
                source_signal_ids=list(d.source_signal_ids or []),
                approval_token=_truncate_token(d.approval_token),
                platform=d.platform,
                created_at=d.created_at,
            )
            for d in drafts
        ],
        signals=[
            TraceSignal(
                signal_id=s.signal_id,
                source=s.source,
                title=s.title,
                url=s.url,
                excerpt=s.excerpt,
            )
            for s in signal_rows
        ],
        turns=[turns_map[tid] for tid in turn_order],
    )


def _truncate_token(token: str | None) -> str | None:
    if not token:
        return token
    if len(token) <= 12:
        return token
    return f"{token[:6]}…{token[-4:]}"
