import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.org import require_company_access
from internal.memory.database import get_db
from internal.memory.repos import (
    get_active_question_run,
    get_company,
    get_latest_question_run,
    get_latest_questions,
)
from internal.perception.question_graph.runner import (
    TRIGGER_GET_MISS,
    TRIGGER_REFRESH,
    start_or_join_run,
)
from schemas.perception import (
    RecommendedQuestionItem,
    RecommendedQuestionsGenerating,
    RecommendedQuestionsResponse,
)

router = APIRouter(prefix="/companies", tags=["questions"])


def _generating_response(
    company_id: uuid.UUID, *, run_id: uuid.UUID | None, status: str
) -> JSONResponse:
    body = RecommendedQuestionsGenerating(
        company_id=company_id, run_id=run_id, status=status
    )
    return JSONResponse(status_code=202, content=body.model_dump(mode="json"))


async def _run_status_for_cache(
    db: AsyncSession, company_id: uuid.UUID, generated_at: datetime
) -> str:
    """Idle unless a run is in-flight, or the latest run failed after this cache."""
    active = await get_active_question_run(db, company_id)
    if active is not None:
        return "running"
    latest = await get_latest_question_run(db, company_id)
    if latest is None or latest.status != "failed":
        return "idle"
    finished = latest.finished_at or latest.started_at
    if finished >= generated_at:
        return "failed"
    return "idle"


@router.get(
    "/{company_id}/recommended-questions",
    response_model=RecommendedQuestionsResponse,
    responses={202: {"model": RecommendedQuestionsGenerating}},
)
async def recommended_questions(
    company_id: Annotated[uuid.UUID, Depends(require_company_access)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RecommendedQuestionsResponse | JSONResponse:
    company = await get_company(db, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    row = await get_latest_questions(db, company_id)
    if row:
        is_stale = row.expires_at <= datetime.now(UTC)
        # Stale cache still serves (ADR 0018: no surprise-cost auto-run).
        # Landing does not force-run; the scheduler replaces the row.
        return RecommendedQuestionsResponse(
            company_id=company_id,
            questions=[RecommendedQuestionItem(**q) for q in row.questions],
            source_signal_ids=row.source_signal_ids,
            generated_at=row.generated_at,
            expires_at=row.expires_at,
            is_stale=is_stale,
            run_status=await _run_status_for_cache(db, company_id, row.generated_at),
        )

    # No cache — the GET miss is the fill trigger (ADR 0018). A terminal failed
    # run is surfaced, not auto-retried on every poll (avoids a cost loop); the
    # SPA retry CTA calls POST refresh.
    latest_run = await get_latest_question_run(db, company_id)
    if latest_run is not None and latest_run.status == "failed":
        return _generating_response(company_id, run_id=latest_run.id, status="failed")
    run, _spawned = await start_or_join_run(company_id=company_id, trigger=TRIGGER_GET_MISS)
    return _generating_response(company_id, run_id=run.id, status=run.status)


@router.post(
    "/{company_id}/recommended-questions/refresh",
    status_code=202,
    response_model=RecommendedQuestionsGenerating,
)
async def refresh_recommended_questions(
    company_id: Annotated[uuid.UUID, Depends(require_company_access)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RecommendedQuestionsGenerating:
    """Force a new run even if the cache is valid. Landing uses this only after a failed empty fill."""
    company = await get_company(db, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    run, _spawned = await start_or_join_run(company_id=company_id, trigger=TRIGGER_REFRESH)
    return RecommendedQuestionsGenerating(company_id=company_id, run_id=run.id, status=run.status)
