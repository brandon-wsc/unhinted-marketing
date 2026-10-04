"""Periodic scheduler: enqueues pipeline jobs onto the Postgres queue (ADR 0039).

The scheduler no longer runs pipelines itself — each tick inserts deduped rows
into ``jobs`` and a ``cmd.worker serve`` process claims them.
"""

import argparse
import asyncio
import hashlib
import logging
import signal
import time
from datetime import UTC, datetime, timedelta

from internal.config import settings
from internal.memory.database import open_session
from internal.memory.repos import enqueue_job, list_companies

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_stop = False


def _handle_sigterm(*_args) -> None:
    global _stop
    _stop = True


def _tick_bucket(interval_seconds: int) -> str:
    """Dedupe scope per tick window — a restart mid-window cannot double-enqueue."""
    return str(int(time.time() // interval_seconds))


async def _enqueue_hot_search_cycle() -> None:
    """Hot tick: one ingest job + one promote job per interval bucket."""
    bucket = _tick_bucket(settings.scheduler_hot_search_interval_minutes * 60)
    async with open_session() as db:
        for kind in ("hot_search", "promote_signals"):
            job = await enqueue_job(db, kind=kind, dedupe_key=f"{kind}:{bucket}")
            if job is not None:
                logger.info("enqueued %s job %s (bucket %s)", kind, job.id, bucket)
        await db.commit()


def _company_jitter_seconds(company_id) -> int:
    """Stable per-company stagger so the 12h tick does not fire all runs at once."""
    digest = hashlib.sha256(f"question-jitter:{company_id}".encode()).hexdigest()
    return int(digest, 16) % 1800


async def _enqueue_questions_cycle(force: bool = False) -> None:
    """Questions tick: one job per company; the jitter becomes ``run_after``."""
    bucket = _tick_bucket(settings.scheduler_questions_interval_hours * 3600)
    now = datetime.now(UTC)
    async with open_session() as db:
        companies = await list_companies(db)
        queued = 0
        for company in companies:
            jitter = 0 if force else _company_jitter_seconds(company.id)
            job = await enqueue_job(
                db,
                kind="questions",
                payload={"company_id": str(company.id)},
                dedupe_key=f"questions:{company.id}:{bucket}",
                run_after=now + timedelta(seconds=jitter),
            )
            if job is not None:
                queued += 1
        await db.commit()
    logger.info(
        "questions: enqueued %d/%d jobs (bucket %s)", queued, len(companies), bucket
    )


async def run_scheduler(*, once: bool = False) -> None:
    signal.signal(signal.SIGINT, _handle_sigterm)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    hot_interval = settings.scheduler_hot_search_interval_minutes * 60
    question_interval = settings.scheduler_questions_interval_hours * 3600
    hot_elapsed = hot_interval
    question_elapsed = question_interval

    if once:
        await _enqueue_hot_search_cycle()
        await _enqueue_questions_cycle(force=True)
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
                await _enqueue_hot_search_cycle()
            except Exception:
                logger.exception("hot-search enqueue failed")

        if question_elapsed >= question_interval:
            question_elapsed = 0
            try:
                await _enqueue_questions_cycle()
            except Exception:
                logger.exception("questions enqueue failed")

    logger.info("Scheduler stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Unhinted marketing scheduler")
    parser.add_argument("--once", action="store_true", help="Enqueue one cycle and exit")
    args = parser.parse_args()
    asyncio.run(run_scheduler(once=args.once))


if __name__ == "__main__":
    main()
