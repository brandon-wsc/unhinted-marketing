"""Worker CLI + service: job queue serve mode, hot search ingest, question
generation, news promotion, admin grants."""

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import socket
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.roles import parse_platform_level
from internal.config import settings
from internal.llm.keys import ByokEncryptionError, encrypt_key, mask_key
from internal.llm.recorder import drain as drain_llm_records
from internal.memory.database import SessionLocal, open_session
from internal.memory.models import Job, User
from internal.memory.repos import (
    claim_next_job,
    finish_job,
    get_company,
    list_top_signals,
    reclaim_stale_jobs,
    reset_market_signals,
    upsert_social_account,
)
from internal.perception.hot_search import ingest_hot_search
from internal.perception.news_promoter import promote_signals
from internal.perception.question_generator import (
    generate_questions_all_companies,
    generate_questions_for_company,
)
from internal.perception.rss_news import ingest_rss_news

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# --- serve: Postgres job queue service mode (ADR 0039) ----------------------

_RECLAIM_INTERVAL_SECONDS = 60
_IDLE_BACKOFF_MAX_SECONDS = 30


async def _job_hot_search(db: AsyncSession, job: Job) -> None:
    counts = await ingest_hot_search(db)
    rss = await ingest_rss_news(db)
    logger.info("job %s hot_search: trends=%s rss=%s", job.id, counts, rss)


async def _job_promote(db: AsyncSession, job: Job) -> None:
    counts = await promote_signals(db)
    logger.info("job %s promote_signals: %s", job.id, counts)


async def _job_questions(db: AsyncSession, job: Job) -> None:
    company_id = job.payload.get("company_id")
    if not company_id:
        raise RuntimeError("questions job missing payload.company_id")
    company = await get_company(db, uuid.UUID(company_id))
    if company is None:
        raise RuntimeError(f"company {company_id} not found")
    result = await generate_questions_for_company(
        db, company, trigger=job.payload.get("trigger"), serving_job_id=job.id
    )
    logger.info("job %s questions: company=%s status=%s", job.id, company_id, result["status"])


# kind → handler. A new job type is one dict entry.
_JOB_HANDLERS: dict[str, Callable[[AsyncSession, Job], Awaitable[None]]] = {
    "hot_search": _job_hot_search,
    "promote_signals": _job_promote,
    "questions": _job_questions,
}


async def _run_one_job(worker_id: str) -> bool:
    """One service tick: claim → dispatch → finish. True when a job ran."""
    async with open_session() as db:
        job = await claim_next_job(db, worker_id=worker_id)
        await db.commit()
        if job is None:
            return False
        logger.info(
            "claimed job %s kind=%s attempt %d/%d",
            job.id,
            job.kind,
            job.attempts,
            job.max_attempts,
        )
        handler = _JOB_HANDLERS.get(job.kind)
        try:
            if handler is None:
                raise RuntimeError(f"unknown job kind {job.kind!r}")
            await handler(db, job)
        except BaseException as exc:
            logger.exception("job %s (%s) raised", job.id, job.kind)
            await db.rollback()
            await finish_job(db, job, ok=False, error=str(exc))
            await db.commit()
            if isinstance(exc, asyncio.CancelledError):
                # Shutdown/cancel mid-job — back to pending, no lease left behind.
                raise
            if job.status == "failed":
                logger.error("job %s (%s) failed: %s", job.id, job.kind, job.error)
            else:
                logger.warning(
                    "job %s (%s) retry %d/%d",
                    job.id,
                    job.kind,
                    job.attempts,
                    job.max_attempts,
                )
        else:
            await finish_job(db, job, ok=True)
            await db.commit()
            logger.info("job %s (%s) succeeded", job.id, job.kind)
        return True


async def _cmd_serve() -> int:
    """Long-running queue consumer (ADR 0039).

    SIGTERM/SIGINT stop claiming new work; the in-flight job finishes first,
    then the loop exits 0. A hard kill leaves a ``running`` lease that the
    reclaim sweep returns to ``pending`` after 15 minutes.
    """
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    logger.info(
        "Worker %s started (poll %ss, reclaim every %ss)",
        worker_id,
        settings.worker_poll_seconds,
        _RECLAIM_INTERVAL_SECONDS,
    )

    last_reclaim = 0.0
    idle_streak = 0
    while not stop.is_set():
        if time.monotonic() - last_reclaim >= _RECLAIM_INTERVAL_SECONDS:
            last_reclaim = time.monotonic()
            try:
                async with open_session() as db:
                    reclaimed = await reclaim_stale_jobs(db)
                    await db.commit()
                if reclaimed:
                    logger.info("reclaimed %d stale job(s)", reclaimed)
            except Exception:
                logger.exception("reclaim sweep failed")

        try:
            ran = await _run_one_job(worker_id)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("worker tick failed")
            ran = False

        if ran:
            idle_streak = 0
            continue
        idle_streak += 1
        # Idle backoff: poll interval doubles on each empty tick, capped.
        delay = min(
            settings.worker_poll_seconds * 2 ** min(idle_streak - 1, 3),
            _IDLE_BACKOFF_MAX_SECONDS,
        )
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=delay)

    await drain_llm_records()
    logger.info("Worker %s stopped", worker_id)
    return 0


async def _cmd_hot_search() -> int:
    async with SessionLocal() as db:
        counts = await ingest_hot_search(db)
        rss = await ingest_rss_news(db)
    print(json.dumps({"trends": counts, "rss": rss}, indent=2))
    errors = counts.get("errors", 0) + rss.get("errors", 0)
    ingested = sum(v for k, v in {**counts, **rss}.items() if k != "errors")
    return 0 if errors == 0 or ingested else 1


async def _cmd_questions(force: bool, company_id: str | None) -> int:
    async with SessionLocal() as db:
        if company_id:
            company = await get_company(db, uuid.UUID(company_id))
            if not company:
                logger.error("Company not found: %s", company_id)
                return 1
            result = await generate_questions_for_company(db, company, force=force)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            results = await generate_questions_all_companies(db, force=force)
            print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


async def _cmd_promote() -> int:
    async with SessionLocal() as db:
        counts = await promote_signals(db)
    print(json.dumps(counts, indent=2))
    return 0


async def _cmd_signals(limit: int) -> int:
    async with SessionLocal() as db:
        rows = await list_top_signals(db, limit=limit, region="HK")
    if not rows:
        print("No HK signals found. Run: python -m cmd.worker hot-search")
        return 1
    for i, s in enumerate(rows, 1):
        rank = (s.metrics or {}).get("rank")
        rank_str = f" #{rank}" if rank else ""
        print(f"{i:2}. [{s.source}]{rank_str} {s.title}")
        if s.excerpt:
            print(f"    {s.excerpt[:120]}")
    return 0


async def _cmd_all(force: bool) -> int:
    rc = await _cmd_hot_search()
    if rc != 0:
        logger.warning("hot-search had errors; continuing")
    await _cmd_promote()
    await _cmd_questions(force=force, company_id=None)
    return 0


async def _cmd_reset_signals(reingest: bool) -> int:
    async with SessionLocal() as db:
        counts = await reset_market_signals(db)
    print(json.dumps({"deleted": counts}, indent=2))
    if not reingest:
        return 0
    logger.info("Re-ingesting Google Trends HK pipeline")
    rc = await _cmd_hot_search()
    if rc != 0:
        logger.warning("hot-search had errors during reingest")
    await _cmd_promote()
    await _cmd_questions(force=True, company_id=None)
    return rc


async def _cmd_set_platform_role(email: str, level: str) -> int:
    """Grant a platform privilege level (ADR 0005) — the only admin bootstrap path."""
    try:
        lvl = parse_platform_level(level)
    except ValueError as exc:
        logger.error("%s", exc)
        return 2
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email.strip().lower()))
        if not user:
            logger.error("User not found: %s", email)
            return 1
        before = user.platform_level
        user.platform_level = int(lvl)
        await db.commit()
    print(
        json.dumps(
            {
                "email": email.strip().lower(),
                "platform_level": {"from": before, "to": int(lvl), "name": lvl.name},
            },
            indent=2,
        )
    )
    return 0


def _parse_expires_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    stamp = datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp


async def _cmd_connect_social_account(
    *,
    company_id: str,
    ig_user_id: str,
    token: str,
    expires_at: str | None,
    platform: str,
) -> int:
    """Store an org Instagram token for Confirm (ADR 0022). Never prints the raw token."""
    platform = (platform or "instagram").strip().lower()
    if platform != "instagram":
        logger.error("Unsupported platform %r (only instagram)", platform)
        return 2
    try:
        cid = uuid.UUID(company_id)
    except ValueError:
        logger.error("Invalid company UUID: %s", company_id)
        return 2
    try:
        expires = _parse_expires_at(expires_at)
    except ValueError:
        logger.error("Invalid --expires-at (use ISO-8601)")
        return 2
    try:
        encrypted = encrypt_key(token)
    except (ByokEncryptionError, ValueError) as exc:
        logger.error("%s", exc)
        return 1
    last4 = mask_key(token)
    async with SessionLocal() as db:
        company = await get_company(db, cid)
        if not company:
            logger.error("Company not found: %s", company_id)
            return 1
        row = await upsert_social_account(
            db,
            company_id=cid,
            platform=platform,
            ig_user_id=ig_user_id.strip(),
            access_token_encrypted=encrypted,
            token_last4=last4,
            expires_at=expires,
            created_by=None,
        )
        await db.commit()
        payload = {
            "id": str(row.id),
            "company_id": str(cid),
            "platform": platform,
            "ig_user_id": ig_user_id.strip(),
            "token_last4": last4,
            "expires_at": expires.isoformat() if expires else None,
        }
    print(json.dumps(payload, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Unhinted marketing workers")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="Run the job-queue worker service (ADR 0039)")
    sub.add_parser("hot-search", help="Ingest Google Trends HK + RSS news")
    q = sub.add_parser("questions", help="Generate recommended questions (12h cache)")
    q.add_argument("--force", action="store_true", help="Ignore cache TTL")
    q.add_argument("--company-id", help="Single company UUID")
    sub.add_parser("promote", help="Promote signals to topic entities in PostgreSQL")
    s = sub.add_parser("signals", help="Print top HK signals (CLI)")
    s.add_argument("--limit", type=int, default=20)
    a = sub.add_parser("all", help="Run hot-search → promote → questions")
    a.add_argument("--force", action="store_true")
    rs = sub.add_parser(
        "reset-signals",
        help="Wipe all market signal data (keeps auth, companies, personas)",
    )
    rs.add_argument(
        "--reingest",
        action="store_true",
        help="After reset, run hot-search → promote → questions --force",
    )
    pr = sub.add_parser("set-platform-role", help="Set a user's platform level (ADR 0005)")
    pr.add_argument("--email", required=True, help="Account email")
    pr.add_argument(
        "--level",
        required=True,
        help="Rung name (member / admin / superadmin) or number (3 / 6 / 9)",
    )
    cs = sub.add_parser(
        "connect-social-account",
        help="Store an org Instagram token for Confirm (ADR 0022)",
    )
    cs.add_argument("--company", required=True, help="Company UUID")
    cs.add_argument("--ig-user-id", required=True, help="Instagram professional account id")
    cs.add_argument("--token", required=True, help="Long-lived Graph access token")
    cs.add_argument("--expires-at", help="ISO-8601 expiry (optional)")
    cs.add_argument("--platform", default="instagram")

    args = parser.parse_args()
    commands = {
        "serve": lambda: _cmd_serve(),
        "hot-search": lambda: _cmd_hot_search(),
        "questions": lambda: _cmd_questions(args.force, getattr(args, "company_id", None)),
        "promote": lambda: _cmd_promote(),
        "signals": lambda: _cmd_signals(args.limit),
        "all": lambda: _cmd_all(args.force),
        "reset-signals": lambda: _cmd_reset_signals(getattr(args, "reingest", False)),
        "set-platform-role": lambda: _cmd_set_platform_role(args.email, args.level),
        "connect-social-account": lambda: _cmd_connect_social_account(
            company_id=args.company,
            ig_user_id=args.ig_user_id,
            token=args.token,
            expires_at=getattr(args, "expires_at", None),
            platform=args.platform,
        ),
    }

    async def _run() -> int:
        rc = await commands[args.command]()
        # Flush pending LLM call records before the loop closes (ADR 0005).
        await drain_llm_records()
        return rc

    rc = asyncio.run(_run())
    sys.exit(rc)


if __name__ == "__main__":
    main()
