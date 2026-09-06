"""Worker CLI: hot search ingest, question generation, news promotion, admin grants."""

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from internal.auth.roles import parse_platform_level
from internal.llm.keys import ByokEncryptionError, encrypt_key, mask_key
from internal.llm.recorder import drain as drain_llm_records
from internal.memory.database import SessionLocal
from internal.memory.models import User
from internal.memory.repos import (
    get_company,
    list_top_signals,
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
