"""Periodic scheduler for hot search and question generation."""

import argparse
import asyncio
import hashlib
import logging
import signal

from internal.config import settings
from internal.llm.recorder import drain as drain_llm_records
from internal.memory.database import SessionLocal
from internal.memory.repos import list_companies
from internal.perception.hot_search import ingest_hot_search
from internal.perception.news_promoter import promote_signals
from internal.perception.question_graph.runner import TRIGGER_SCHEDULER, run_company_now
from internal.perception.rss_news import ingest_rss_news

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_stop = False


def _handle_sigterm(*_args) -> None:
    global _stop
    _stop = True


async def _run_hot_search_cycle() -> None:
    async with SessionLocal() as db:
        counts = await ingest_hot_search(db)
        logger.info("hot-search: %s", counts)
        rss = await ingest_rss_news(db)
        logger.info("rss-news: %s", rss)
        promo = await promote_signals(db)
        logger.info("promote: %s", promo)


def _company_jitter_seconds(company_id) -> int:
    """Stable per-company stagger so the 12h tick does not fire all runs at once."""
    digest = hashlib.sha256(f"question-jitter:{company_id}".encode()).hexdigest()
    return int(digest, 16) % 1800


async def _run_questions_cycle(force: bool = False) -> None:
    async with SessionLocal() as db:
        companies = await list_companies(db)
    # Same graph + runner as the HTTP fill path (ADR 0018); the runner's global
    # semaphore caps concurrency across the fan-out.
    results = await asyncio.gather(
        *(
            run_company_now(
                company,
                trigger=TRIGGER_SCHEDULER,
                jitter_seconds=0 if force else _company_jitter_seconds(company.id),
            )
            for company in companies
        ),
        return_exceptions=True,
    )
    ok = 0
    failed = 0
    for company, result in zip(companies, results, strict=True):
        if isinstance(result, Exception):
            failed += 1
            logger.exception("questions cycle failed for %s", company.id, exc_info=result)
        elif getattr(result, "status", None) == "succeeded":
            ok += 1
        else:
            failed += 1
    logger.info("questions: %d succeeded, %d failed/skipped", ok, failed)
    # Flush pending LLM call records before the next sleep (ADR 0005).
    await drain_llm_records()


async def run_scheduler(*, once: bool = False) -> None:
    signal.signal(signal.SIGINT, _handle_sigterm)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    hot_interval = settings.scheduler_hot_search_interval_minutes * 60
    question_interval = settings.scheduler_questions_interval_hours * 3600
    hot_elapsed = hot_interval
    question_elapsed = question_interval

    if once:
        await _run_hot_search_cycle()
        await _run_questions_cycle(force=True)
        return

    logger.info(
        "Scheduler started (hot-search every %sm, questions every %sh)",
        settings.scheduler_hot_search_interval_minutes,
        settings.scheduler_questions_interval_hours,
    )

    while not _stop:
        await asyncio.sleep(60)
        hot_elapsed += 60
        question_elapsed += 60

        if hot_elapsed >= hot_interval:
            hot_elapsed = 0
            try:
                await _run_hot_search_cycle()
            except Exception:
                logger.exception("hot-search cycle failed")

        if question_elapsed >= question_interval:
            question_elapsed = 0
            try:
                await _run_questions_cycle()
            except Exception:
                logger.exception("questions cycle failed")

    logger.info("Scheduler stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Unhinted marketing scheduler")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args()
    asyncio.run(run_scheduler(once=args.once))


if __name__ == "__main__":
    main()
