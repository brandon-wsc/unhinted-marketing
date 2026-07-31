"""Worker CLI: hot search ingest, question generation, news promotion."""

import argparse
import asyncio
import json
import logging
import sys

from internal.memory.database import SessionLocal
from internal.perception.hot_search import ingest_hot_search
from internal.perception.news_promoter import promote_signals
from internal.perception.question_generator import (
    generate_questions_all_companies,
    generate_questions_for_company,
)
from internal.memory.repos import get_company, list_top_signals, reset_market_signals

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

    args = parser.parse_args()
    commands = {
        "hot-search": lambda: _cmd_hot_search(),
        "questions": lambda: _cmd_questions(args.force, getattr(args, "company_id", None)),
        "promote": lambda: _cmd_promote(),
        "signals": lambda: _cmd_signals(args.limit),
        "all": lambda: _cmd_all(args.force),
        "reset-signals": lambda: _cmd_reset_signals(getattr(args, "reingest", False)),
    }
    rc = asyncio.run(commands[args.command]())
    sys.exit(rc)


if __name__ == "__main__":
    main()
