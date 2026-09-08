"""Admin read APIs (ADR 0005 / Trace viewer) — gated by platform level, never tenant RBAC."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.roles import PlatformLevel, require_platform_level
from internal.media.storage import resolve_stored_url
from internal.memory import repos
from internal.memory.database import get_db
from internal.memory.models import (
    LlmCallRecord,
    PreviewDraft,
    QuestionRun,
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
    QuestionNodeStepList,
    QuestionNodeStepSummary,
    QuestionRunList,
    QuestionRunSummary,
    ResearchSignalHit,
    ResearchTurn,
    SessionResearch,
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
                image_url=resolve_stored_url(d.image_url),
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


@router.get("/sessions/{session_id}/research", response_model=SessionResearch)
async def get_session_research(
    session_id: uuid.UUID,
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionResearch:
    """Aggregate ADR 0009 research gate + Tavily∪PG ingest from node-step outputs."""
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    steps = (
        await db.scalars(
            select(SessionNodeStep)
            .where(SessionNodeStep.session_id == session_id)
            .order_by(asc(SessionNodeStep.created_at), asc(SessionNodeStep.seq))
        )
    ).all()

    research_nodes = {
        "fast_rule_checker",
        "route_intent",
        "query_generator",
        "research_ingest",
    }
    turns_map: dict[uuid.UUID, ResearchTurn] = {}
    turn_order: list[uuid.UUID] = []

    def _ensure(tid: uuid.UUID, created_at: datetime | None) -> ResearchTurn:
        if tid not in turns_map:
            turns_map[tid] = ResearchTurn(turn_id=tid, created_at=created_at)
            turn_order.append(tid)
        return turns_map[tid]

    for step in steps:
        if step.node not in research_nodes:
            continue
        turn = _ensure(step.turn_id, step.created_at)
        if turn.created_at is None:
            turn.created_at = step.created_at
        out = step.output if isinstance(step.output, dict) else {}
        research = out.get("research") if isinstance(out.get("research"), dict) else {}

        if step.node == "fast_rule_checker":
            if "research_rule_pass" in out:
                turn.research_rule_pass = bool(out.get("research_rule_pass"))
            if research.get("semantic_route") is not None:
                turn.semantic_route = str(research.get("semantic_route"))
        elif step.node == "route_intent":
            if "research_rule_pass" in out:
                turn.research_rule_pass = bool(out.get("research_rule_pass"))
            if "need_facts" in research:
                turn.need_facts = bool(research.get("need_facts"))
            if "ambiguous" in research:
                turn.ambiguous = bool(research.get("ambiguous"))
            if "ask_clarify" in research:
                turn.ask_clarify = bool(research.get("ask_clarify"))
            if research.get("entity_surface"):
                turn.entity_surface = str(research.get("entity_surface"))
            if research.get("semantic_route") is not None:
                turn.semantic_route = str(research.get("semantic_route"))
        elif step.node == "query_generator":
            if out.get("search_query"):
                turn.search_query = str(out.get("search_query"))
            qs = research.get("search_queries") or out.get("search_queries")
            if isinstance(qs, list):
                turn.search_queries = [str(q) for q in qs if q]
            elif turn.search_query:
                turn.search_queries = [turn.search_query]
        elif step.node == "research_ingest":
            turn.ran_research_ingest = True
            if out.get("search_query"):
                turn.search_query = str(out.get("search_query"))
            qs = research.get("search_queries") or out.get("search_queries")
            if isinstance(qs, list) and qs:
                turn.search_queries = [str(q) for q in qs if q]
            if research.get("query_source"):
                turn.query_source = str(research.get("query_source"))
            if "signals_trusted" in research:
                turn.signals_trusted = bool(research.get("signals_trusted"))
            ids = out.get("source_signal_ids")
            if isinstance(ids, list):
                turn.source_signal_ids = [str(i) for i in ids if i]
            signals_raw = out.get("research_signals")
            hits: list[ResearchSignalHit] = []
            if isinstance(signals_raw, list):
                for row in signals_raw:
                    if not isinstance(row, dict):
                        continue
                    sid = row.get("signal_id")
                    if not sid:
                        continue
                    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
                    hits.append(
                        ResearchSignalHit(
                            signal_id=str(sid),
                            source=str(row.get("source") or ""),
                            title=str(row.get("title") or ""),
                            url=str(row["url"]) if row.get("url") else None,
                            excerpt=str(row["excerpt"]) if row.get("excerpt") else None,
                            query=str(metrics["query"]) if metrics.get("query") else None,
                        )
                    )
            turn.signals = hits

    return SessionResearch(
        session_id=session_id,
        turns=[turns_map[tid] for tid in turn_order],
    )


async def _question_run_cost(db: AsyncSession, run: QuestionRun) -> dict[str, int]:
    stmt = select(
        func.count(LlmCallRecord.id),
        func.coalesce(func.sum(LlmCallRecord.prompt_tokens), 0),
        func.coalesce(func.sum(LlmCallRecord.completion_tokens), 0),
        func.coalesce(func.sum(LlmCallRecord.total_tokens), 0),
    ).where(
        LlmCallRecord.company_id == run.company_id,
        LlmCallRecord.caller.like("node:question_%"),
        LlmCallRecord.created_at >= run.started_at,
    )
    if run.finished_at is not None:
        stmt = stmt.where(LlmCallRecord.created_at <= run.finished_at)
    row = (await db.execute(stmt)).one()
    return {
        "llm_calls": int(row[0] or 0),
        "prompt_tokens": int(row[1] or 0),
        "completion_tokens": int(row[2] or 0),
        "total_tokens": int(row[3] or 0),
    }


@router.get("/companies/{company_id}/question-runs", response_model=QuestionRunList)
async def list_question_runs(
    company_id: uuid.UUID,
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> QuestionRunList:
    runs = await repos.list_question_runs(db, company_id, limit=limit)
    items: list[QuestionRunSummary] = []
    for run in runs:
        cost = await _question_run_cost(db, run)
        items.append(QuestionRunSummary.model_validate(run).model_copy(update=cost))
    return QuestionRunList(items=items, limit=limit)


@router.get("/question-runs/{run_id}/steps", response_model=QuestionNodeStepList)
async def list_question_run_steps(
    run_id: uuid.UUID,
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuestionNodeStepList:
    run = await db.get(QuestionRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    steps = await repos.list_question_node_steps(db, run_id)
    return QuestionNodeStepList(
        items=[QuestionNodeStepSummary.model_validate(s) for s in steps]
    )


def _truncate_token(token: str | None) -> str | None:
    if not token:
        return token
    if len(token) <= 12:
        return token
    return f"{token[:6]}…{token[-4:]}"
