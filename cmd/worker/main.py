"""Worker CLI: hot search ingest, question generation, news promotion, admin grants."""

import argparse
import asyncio
import json
import logging
import sys

from sqlalchemy import select

from internal.auth.roles import parse_platform_level
from internal.llm.recorder import drain as drain_llm_records
from internal.memory.database import SessionLocal
from internal.memory.models import User
from internal.memory.repos import get_company, list_top_signals, reset_market_signals
from internal.perception.hot_search import ingest_hot_search
from internal.perception.news_promoter import promote_signals
from internal.perception.question_generator import (
    generate_questions_all_companies,
    generate_questions_for_company,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def _cmd_hot_search() -> int:
    async with SessionLocal() as db:
        counts = await ingest_hot_search(db)
    print(json.dumps(counts, indent=2))
    return 0 if counts.get("errors", 0) == 0 or sum(v for k, v in counts.items() if k != "errors") else 1


async def _cmd_questions(force: bool, company_id: str | None) -> int:
    async with SessionLocal() as db:
        if company_id:
            from uuid import UUID

            company = await get_company(db, UUID(company_id))
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Unhinted marketing workers")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("hot-search", help="Ingest Google Trends HK")
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

    args = parser.parse_args()
    commands = {
        "hot-search": lambda: _cmd_hot_search(),
        "questions": lambda: _cmd_questions(args.force, getattr(args, "company_id", None)),
        "promote": lambda: _cmd_promote(),
        "signals": lambda: _cmd_signals(args.limit),
        "all": lambda: _cmd_all(args.force),
        "reset-signals": lambda: _cmd_reset_signals(getattr(args, "reingest", False)),
        "set-platform-role": lambda: _cmd_set_platform_role(args.email, args.level),
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
