import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.org import require_company_access
from internal.memory.database import get_db
from internal.memory.repos import get_company, get_latest_questions
from schemas.perception import RecommendedQuestionItem, RecommendedQuestionsResponse

router = APIRouter(prefix="/companies", tags=["questions"])


@router.get("/{company_id}/recommended-questions", response_model=RecommendedQuestionsResponse)
async def recommended_questions(
    company_id: Annotated[uuid.UUID, Depends(require_company_access)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RecommendedQuestionsResponse:
    company = await get_company(db, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    row = await get_latest_questions(db, company_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail="No recommended questions yet — run the question-generator worker",
        )

    is_stale = row.expires_at <= datetime.now(UTC)
    return RecommendedQuestionsResponse(
        company_id=company_id,
        questions=[RecommendedQuestionItem(**q) for q in row.questions],
        source_signal_ids=row.source_signal_ids,
        generated_at=row.generated_at,
        expires_at=row.expires_at,
        is_stale=is_stale,
    )
