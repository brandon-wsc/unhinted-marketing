"""Periodic scheduler for hot search and question generation."""

import argparse
import asyncio
import logging
import signal

from internal.config import settings
from internal.memory.database import SessionLocal
from internal.perception.hot_search import ingest_hot_search
from internal.perception.news_promoter import promote_signals
from internal.perception.question_generator import generate_questions_all_companies

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
        promo = await promote_signals(db)
        logger.info("promote: %s", promo)


async def _run_questions_cycle(force: bool = False) -> None:
    async with SessionLocal() as db:
        results = await generate_questions_all_companies(db, force=force)
        logger.info("questions generated for %d companies", len(results))


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
