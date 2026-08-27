"""Question run lifecycle (ADR 0018): dedupe, semaphore, persistence, spawn.

Dedupe is DB-enforced (partial unique index on one running run per company) —
multi-worker safe, no in-memory futures. The API spawns runs as background
tasks; the scheduler/CLI may also drive runs inline via ``run_company_now``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from internal.config import settings
from internal.memory.database import SessionLocal
from internal.memory.knowledge_seed import ensure_default_personas
from internal.memory.models import Entity, QuestionRun
from internal.memory.repos import (
    create_question_run,
    finish_question_run,
    get_active_question_run,
    get_company,
    get_latest_question_run,
    list_personas,
    list_products,
    list_recent_question_history,
    save_recommended_questions,
)
from internal.perception.question_graph.context import question_db
from internal.perception.question_graph.graph import get_question_graph
from internal.perception.question_graph.state import QuestionGraphState
from internal.session.voice import audience_catalog_from_entities, voice_pack

logger = logging.getLogger(__name__)

TRIGGER_GET_MISS = "get_miss"
TRIGGER_REFRESH = "refresh"
TRIGGER_SCHEDULER = "scheduler"

_background_tasks: set[asyncio.Task] = set()
_live_run_ids: set[uuid.UUID] = set()
_semaphore: asyncio.Semaphore | None = None
_GRAPH_TIMEOUT = timedelta(minutes=6)
_REFRESH_ABANDON_AFTER = timedelta(seconds=45)
_JOIN_ABANDON_AFTER = timedelta(minutes=2)


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.question_run_max_concurrency)
    return _semaphore


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _sweep_stale_run(db: AsyncSession, company_id: uuid.UUID) -> QuestionRun | None:
    """A crashed worker leaves `running` rows; expire them so fill can retry."""
    active = await get_active_question_run(db, company_id)
    if active is None:
        return None
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.question_run_stale_minutes)
    if _as_aware(active.started_at) < cutoff:
        await finish_question_run(
            db, active, status="failed", error="stale: exceeded max run time"
        )
        await db.commit()
        return None
    return active


def _should_abandon(active: QuestionRun, trigger: str) -> bool:
    """Join only if this process is still running the graph (or it just started).

    uvicorn --reload and crashes leave ``running`` rows with no task. POST refresh
    used to join those zombies, so the SPA polled old cache until it gave up.
    """
    if active.id in _live_run_ids:
        return False
    age = datetime.now(UTC) - _as_aware(active.started_at)
    if trigger == TRIGGER_REFRESH:
        return age > _REFRESH_ABANDON_AFTER
    return age > _JOIN_ABANDON_AFTER


async def start_or_join_run(
    *, company_id: uuid.UUID, trigger: str
) -> tuple[QuestionRun, bool]:
    """Return (run, spawned). One active run per company; callers join in-flight runs."""
    async with SessionLocal() as db:
        active = await _sweep_stale_run(db, company_id)
        if active is not None and _should_abandon(active, trigger):
            await finish_question_run(
                db, active, status="failed", error="abandoned: worker lost the run"
            )
            await db.commit()
            logger.warning(
                "abandoned question run %s for company %s (trigger=%s)",
                active.id,
                company_id,
                trigger,
            )
            active = None
        if active is not None:
            return active, False
        run: QuestionRun | None = None
        try:
            run = await create_question_run(db, company_id=company_id, trigger=trigger)
            _live_run_ids.add(run.id)
            await db.commit()
        except IntegrityError:
            # Another worker won the race (partial unique index) — join theirs.
            await db.rollback()
            if run is not None:
                _live_run_ids.discard(run.id)
            active = await get_active_question_run(db, company_id)
            if active is not None:
                return active, False
            latest = await get_latest_question_run(db, company_id)
            if latest is not None:
                return latest, False
            raise

    _spawn(run.id, company_id)
    return run, True


def _spawn(run_id: uuid.UUID, company_id: uuid.UUID) -> None:
    _live_run_ids.add(run_id)
    task = asyncio.create_task(_execute_guarded(run_id=run_id, company_id=company_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def run_company_now(
    company: Entity, *, trigger: str, jitter_seconds: int = 0
) -> QuestionRun | None:
    """Inline path for scheduler/CLI: dedupe, optional stagger, then execute."""
    if jitter_seconds > 0:
        await asyncio.sleep(jitter_seconds)
    async with SessionLocal() as db:
        active = await _sweep_stale_run(db, company.id)
        if active is not None and _should_abandon(active, trigger):
            await finish_question_run(
                db, active, status="failed", error="abandoned: worker lost the run"
            )
            await db.commit()
            active = None
        if active is not None:
            logger.info("question run already active for company %s — skipping", company.id)
            return active
        run: QuestionRun | None = None
        try:
            run = await create_question_run(db, company_id=company.id, trigger=trigger)
            _live_run_ids.add(run.id)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            if run is not None:
                _live_run_ids.discard(run.id)
            return await get_active_question_run(db, company.id)
    assert run is not None
    await _execute_guarded(run_id=run.id, company_id=company.id)
    async with SessionLocal() as db:
        return await db.get(QuestionRun, run.id)


async def _execute_guarded(*, run_id: uuid.UUID, company_id: uuid.UUID) -> None:
    _live_run_ids.add(run_id)
    try:
        async with _get_semaphore(), SessionLocal() as db:
            try:
                await _execute(db, run_id=run_id, company_id=company_id)
            except Exception as exc:
                logger.exception("question run %s failed", run_id)
                try:
                    await db.rollback()
                    run = await db.get(QuestionRun, run_id)
                    if run is not None and run.status == "running":
                        await finish_question_run(
                            db, run, status="failed", error=str(exc)[:500]
                        )
                        await db.commit()
                except Exception:
                    logger.exception("failed to mark question run %s failed", run_id)
    finally:
        _live_run_ids.discard(run_id)


async def _execute(db: AsyncSession, *, run_id: uuid.UUID, company_id: uuid.UUID) -> None:
    company = await get_company(db, company_id)
    if company is None:
        raise RuntimeError(f"company {company_id} not found")

    await ensure_default_personas(db)
    personas = await list_personas(db)
    products = await list_products(db, company_id=company_id, owner_scope="org")
    run = await db.get(QuestionRun, run_id)
    # Manual refresh is replacing the current cards — don't trend-combo-skip
    # those signal ids or compose can return 0 and leave the old cache in place.
    history = await list_recent_question_history(
        db,
        company_id,
        days=settings.question_dedupe_days,
        skip_latest=run is not None and run.trigger == TRIGGER_REFRESH,
    )

    state: QuestionGraphState = {
        "run_id": str(run_id),
        "company_id": str(company_id),
        "company_name": company.name,
        "company_slug": company.slug,
        "profile": dict(company.profile or {}),
        "voice": voice_pack(company.profile),
        "audience": audience_catalog_from_entities(personas),
        "product_names": [p.name for p in products],
        "recent_texts": history["texts"],
        "recent_signal_ids": history["signal_ids"],
        "quality_flags": [],
    }

    graph = get_question_graph()
    with question_db(db):
        final = await asyncio.wait_for(
            graph.ainvoke(state), timeout=_GRAPH_TIMEOUT.total_seconds()
        )

    questions = final.get("questions") or []
    if not questions:
        raise RuntimeError("question graph produced no questions")

    await save_recommended_questions(
        db,
        company_id=company_id,
        questions=questions,
        source_signal_ids=final.get("used_signal_ids") or [],
        ttl_hours=settings.question_cache_ttl_hours,
    )
    run = await db.get(QuestionRun, run_id)
    if run is not None:
        await finish_question_run(
            db, run, status="succeeded", quality_flags=final.get("quality_flags") or []
        )
    await db.commit()
