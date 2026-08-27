"""Compatibility wrapper — question generation is the ADR 0018 worker graph.

The graph runner owns dedupe / run records / persistence; this module keeps the
worker CLI + scheduler call sites stable.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory.models import Entity
from internal.memory.repos import get_latest_questions, list_companies
from internal.perception.question_graph.runner import (
    TRIGGER_REFRESH,
    TRIGGER_SCHEDULER,
    run_company_now,
)

logger = logging.getLogger(__name__)


async def generate_questions_for_company(
    db: AsyncSession,
    company: Entity,
    *,
    force: bool = False,
) -> dict:
    run = await run_company_now(
        company, trigger=TRIGGER_REFRESH if force else TRIGGER_SCHEDULER
    )
    latest = await get_latest_questions(db, company.id)
    return {
        "company_id": str(company.id),
        "run_id": str(run.id) if run else None,
        "status": run.status if run else None,
        "questions": latest.questions if latest else [],
        "source_signal_ids": latest.source_signal_ids if latest else [],
    }


async def generate_questions_all_companies(db: AsyncSession, *, force: bool = False) -> list[dict]:
    results = []
    for company in await list_companies(db):
        try:
            results.append(await generate_questions_for_company(db, company, force=force))
        except Exception:
            logger.exception("Question generation failed for company %s", company.id)
    return results
