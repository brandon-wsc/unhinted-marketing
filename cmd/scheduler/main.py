"""Periodic scheduler: enqueues pipeline jobs onto the Postgres queue (ADR 0039).

The scheduler no longer runs pipelines itself — each tick inserts deduped rows
into ``jobs`` and a ``cmd.worker serve`` process claims them.
"""

import argparse
import asyncio
import contextlib
import hashlib
import logging
import signal
import time
from datetime import UTC, datetime, timedelta

from internal.config import settings
from internal.instance.config import InstanceSnapshot, load_snapshot
from internal.memory.database import open_session
from internal.memory.repos import enqueue_job, list_companies

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_stop = False
_stop_event: asyncio.Event | None = None


def _handle_sigterm(*_args) -> None:
    global _stop
    _stop = True
    if _stop_event is not None:
        _stop_event.set()


def _tick_bucket(interval_seconds: int) -> str:
    """Dedupe scope per tick window — a restart mid-window cannot double-enqueue."""
    return str(int(time.time() // interval_seconds))


async def _enqueue_hot_search_cycle(snap: InstanceSnapshot) -> None:
    """Hot tick: one ingest job + one promote job per interval bucket."""
    bucket = _tick_bucket(snap.scheduler_hot_search_interval_minutes * 60)
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


async def _enqueue_questions_cycle(snap: InstanceSnapshot, force: bool = False) -> None:
    """Questions tick: one job per company; the jitter becomes ``run_after``."""
    bucket = _tick_bucket(snap.scheduler_questions_interval_hours * 3600)
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


async def _current_snapshot() -> InstanceSnapshot:
    """ADR 0050 — re-read instance settings each tick so portal edits apply
    within ~1 minute without a scheduler restart."""
    async with open_session() as db:
        return await load_snapshot(db)


async def _run_polling(snap: InstanceSnapshot) -> None:
    """Legacy cadence — 60s loop with a snapshot reload per tick (ADR 0050)."""
    hot_elapsed = snap.scheduler_hot_search_interval_minutes * 60
    question_elapsed = snap.scheduler_questions_interval_hours * 3600

    while not _stop:
        await asyncio.sleep(60)
        hot_elapsed += 60
        question_elapsed += 60

        try:
            snap = await _current_snapshot()
        except Exception:
            logger.exception("instance snapshot reload failed; keeping last values")

        if (
            snap.scheduler_hot_search_enabled
            and hot_elapsed >= snap.scheduler_hot_search_interval_minutes * 60
        ):
            hot_elapsed = 0
            try:
                await _enqueue_hot_search_cycle(snap)
            except Exception:
                logger.exception("hot-search enqueue failed")

        if question_elapsed >= snap.scheduler_questions_interval_hours * 3600:
            question_elapsed = 0
            try:
                await _enqueue_questions_cycle(snap)
            except Exception:
                logger.exception("questions enqueue failed")


async def _run_quiet(snap: InstanceSnapshot) -> None:
    """ADR 0058 §9 — resident but silent: sleep until a tick is due or a kick
    arrives; reload the snapshot on every wake so portal edits keep ADR 0050's
    ~1-minute apply without a 60s DB read."""
    from internal.memory import wake as wake_lib

    kick_ev = asyncio.Event()
    server, task = await wake_lib.serve_kick(settings.kick_port, kick_ev.set)
    logger.info("Scheduler quiet mode (kick port %s)", settings.kick_port)
    try:
        hot_fired = question_fired = time.monotonic()
        while not _stop:
            due_in = [question_fired + snap.scheduler_questions_interval_hours * 3600]
            if snap.scheduler_hot_search_enabled:
                due_in.append(
                    hot_fired + snap.scheduler_hot_search_interval_minutes * 60
                )
            delay = max(1.0, min(due_in) - time.monotonic())
            reason = await wake_lib.wait_for_trigger(_stop_event, kick_ev, delay)
            if reason == "stop":
                break

            try:
                snap = await _current_snapshot()
            except Exception:
                logger.exception(
                    "instance snapshot reload failed; keeping last values"
                )

            now = time.monotonic()
            if snap.scheduler_hot_search_enabled and now >= (
                hot_fired + snap.scheduler_hot_search_interval_minutes * 60
            ):
                hot_fired = now
                try:
                    await _enqueue_hot_search_cycle(snap)
                except Exception:
                    logger.exception("hot-search enqueue failed")

            if now >= (
                question_fired + snap.scheduler_questions_interval_hours * 3600
            ):
                question_fired = now
                try:
                    await _enqueue_questions_cycle(snap)
                except Exception:
                    logger.exception("questions enqueue failed")
    finally:
        server.should_exit = True
        with contextlib.suppress(Exception):
            await task
    logger.info("Scheduler stopped")


async def run_scheduler(*, once: bool = False) -> None:
    global _stop_event
    signal.signal(signal.SIGINT, _handle_sigterm)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    snap = await _current_snapshot()

    if once:
        await _enqueue_hot_search_cycle(snap)
        await _enqueue_questions_cycle(snap, force=True)
        return

    logger.info(
        "Scheduler started (hot-search every %sm, questions every %sh)",
        snap.scheduler_hot_search_interval_minutes,
        snap.scheduler_questions_interval_hours,
    )

    if settings.kick_port:
        _stop_event = asyncio.Event()
        await _run_quiet(snap)
    else:
        await _run_polling(snap)

    logger.info("Scheduler stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Unhinted scheduler")
    parser.add_argument("--once", action="store_true", help="Enqueue one cycle and exit")
    args = parser.parse_args()
    asyncio.run(run_scheduler(once=args.once))


if __name__ == "__main__":
    main()
