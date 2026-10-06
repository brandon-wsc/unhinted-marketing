"""On-demand product-retrieve eval against a seeded pgvector catalog.

Keyless and deterministic: seeds a fixed catalog fixture with real FastEmbed
embeddings into a scratch Postgres, then exercises the real
``search_products_for_member`` path (lexical + pgvector Tier C + RRF).

Never touches DATABASE_URL — point ``EVAL_DATABASE_URL`` (or
``TEST_DATABASE_URL``) at a disposable database. The script runs
``alembic upgrade head`` against it and truncates ``products`` before seeding.

Usage (repo root, after `pip install -e ".[dev]"`):

    createdb unhinted_eval   # on your pgvector Postgres
    EVAL_DATABASE_URL=postgresql+asyncpg://…/unhinted_eval \
        python -m scripts.eval_retrieve
    python -m scripts.eval_retrieve --db-url postgresql+asyncpg://…/unhinted_eval \
        --out reports/eval/retrieve-baseline.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from internal.config import settings
from internal.memory.database import attach_pgvector
from internal.memory.embeddings import embed_query, start_product_embedder_warmup
from internal.memory.models import Entity, User
from internal.memory.product_import import build_search_document
from internal.memory.product_retrieve import (
    pick_primary,
    search_products_for_member,
)
from internal.memory.repos import upsert_product_row
from tests.eval.graders import grade_retrieve

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOGS_DIR = REPO_ROOT / "tests" / "eval" / "catalogs"
DEFAULT_CASES_DIR = REPO_ROOT / "tests" / "eval" / "retrieve_cases"
REPORT_DIR = REPO_ROOT / "reports" / "eval"

_FIXED_NS = uuid.UUID("e5e5e5e5-1111-4222-8333-444444444444")


def _eval_db_url(cli: str | None) -> str:
    url = (cli or "").strip() or os.environ.get("EVAL_DATABASE_URL", "").strip()
    url = url or os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "Set EVAL_DATABASE_URL (or TEST_DATABASE_URL) to a disposable "
            "pgvector database — never DATABASE_URL."
        )
    if url == os.environ.get("DATABASE_URL", "").strip():
        raise SystemExit("Refusing to run against DATABASE_URL — use a scratch DB.")
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


def _migrate(url: str) -> None:
    env = {**os.environ, "DATABASE_URL": url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )


def _load_yaml_dir(path: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for file in sorted(path.glob("*.yaml")):
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
        if data is None:
            continue
        docs.extend(data if isinstance(data, list) else [data])
    return docs


def _fixture_ids(catalog_id: str) -> tuple[uuid.UUID, uuid.UUID]:
    company_id = uuid.uuid5(_FIXED_NS, f"catalog:{catalog_id}:company")
    user_id = uuid.uuid5(_FIXED_NS, f"catalog:{catalog_id}:user")
    return company_id, user_id


async def _warm_embedder(timeout_s: int) -> None:
    """FastEmbed loads/downloads in a daemon thread — block until ready."""
    if not settings.product_embeddings_enabled:
        print("product_embeddings_enabled=false — vector tier disabled")
        return
    start_product_embedder_warmup()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await asyncio.to_thread(embed_query, "warmup"):
            return
        await asyncio.sleep(0.5)
    raise SystemExit(f"Embedder not ready after {timeout_s}s — check model download")


async def _seed_catalog(
    session_factory: async_sessionmaker[AsyncSession], catalog: dict[str, Any]
) -> tuple[uuid.UUID, uuid.UUID]:
    catalog_id = str(catalog.get("id") or "unnamed")
    company_id, user_id = _fixture_ids(catalog_id)
    async with session_factory() as db:
        # Idempotent reseed: entity delete cascades products (FK CASCADE).
        await db.execute(delete(Entity).where(Entity.id == company_id))
        await db.execute(delete(User).where(User.id == user_id))
        # Deterministic tenant + member rows; membership is not required for
        # retrieve (repo filters on company_id/owner_scope/user_id only).
        db.add(
            Entity(
                id=company_id,
                entity_type="company",
                slug=f"eval-{catalog_id}",
                name=f"Eval Co ({catalog_id})",
            )
        )
        db.add(
            User(
                id=user_id,
                email=f"eval-{catalog_id}@example.test",
                password_hash="eval",
                display_name="Eval User",
            )
        )
        await db.flush()
        for row in catalog.get("products") or []:
            scope = str(row.get("scope") or "org")
            profile = {str(k): str(v) for k, v in (row.get("profile") or {}).items()}
            await upsert_product_row(
                db,
                company_id=company_id,
                owner_scope=scope,
                user_id=user_id if scope == "user" else None,
                sku=str(row["sku"]),
                name=str(row["name"]),
                search_document=build_search_document(
                    profile, sku=str(row["sku"]), name=str(row["name"])
                ),
                profile=profile,
                embed=True,
            )
        await db.commit()
    return company_id, user_id


async def _run_case(
    db: AsyncSession,
    case: dict[str, Any],
    company_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    queries = [str(q) for q in (case.get("queries") or [])]
    limit = int(case.get("limit") or 5)
    hits = await search_products_for_member(
        db, company_id=company_id, user_id=user_id, queries=queries, limit=limit
    )
    primary, clarify = pick_primary(hits)
    return {
        "hits": [
            {
                "sku": h.product.sku,
                "score": round(h.score, 4),
                "match_kind": h.match_kind,
            }
            for h in hits
        ],
        "primary_sku": primary.product.sku if primary else None,
        "primary_kind": primary.match_kind if primary else None,
        "clarify": clarify,
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    url = _eval_db_url(args.db_url)
    catalogs = {str(c.get("id")): c for c in _load_yaml_dir(args.catalogs)}
    cases = _load_yaml_dir(args.cases)
    if not cases:
        raise SystemExit(f"no cases in {args.cases}")

    await _warm_embedder(args.warmup_timeout)
    _migrate(url)
    engine = create_async_engine(url, echo=False, pool_pre_ping=True)
    attach_pgvector(engine)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    seeded: dict[str, tuple[uuid.UUID, uuid.UUID]] = {}
    rows: list[dict[str, Any]] = []
    try:
        async with session_factory() as db:
            for case in cases:
                cid = str(case.get("id") or "unnamed")
                catalog_id = str(case.get("catalog") or "")
                catalog = catalogs.get(catalog_id)
                if catalog is None:
                    rows.append(
                        {
                            "id": cid,
                            "passed": False,
                            "reasons": [f"unknown catalog {catalog_id!r}"],
                            "output": {},
                        }
                    )
                    continue
                if catalog_id not in seeded:
                    seeded[catalog_id] = await _seed_catalog(session_factory, catalog)
                company_id, user_id = seeded[catalog_id]
                start = time.monotonic()
                try:
                    output = await _run_case(db, case, company_id, user_id)
                    reasons = grade_retrieve(output, case.get("expect") or {})
                except Exception as exc:  # noqa: BLE001 — per-case isolation
                    output = {}
                    reasons = [f"{type(exc).__name__}: {exc}"]
                rows.append(
                    {
                        "id": cid,
                        "catalog": catalog_id,
                        "passed": not reasons,
                        "reasons": reasons,
                        "latency_ms": int((time.monotonic() - start) * 1000),
                        "output": output,
                    }
                )
    finally:
        await engine.dispose()

    passed = sum(1 for r in rows if r["passed"])
    return {
        "suite": "retrieve",
        "when": datetime.now(UTC).isoformat(),
        "ok": passed == len(rows),
        "passed": passed,
        "total": len(rows),
        "embedding_model": settings.product_embedding_model
        or settings.semantic_router_model,
        "cases": rows,
    }


def _print_table(report: dict[str, Any]) -> None:
    print(f"{'id':<34} {'pass':<6} {'ms':>6}  reason")
    print("-" * 90)
    for row in report["cases"]:
        reason = "; ".join(row["reasons"]) if row["reasons"] else ""
        mark = "ok" if row["passed"] else "FAIL"
        print(f"{row['id']:<34} {mark:<6} {row.get('latency_ms', 0):>6}  {reason}")
        for hit in (row.get("output") or {}).get("hits") or []:
            print(
                f"    {hit['sku']:<18} {hit['score']:>6.3f}  {hit['match_kind']}"
            )
    print(
        f"\n{report['passed']}/{report['total']} passed — "
        f"model={report['embedding_model']}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db-url", default=None)
    ap.add_argument("--catalogs", type=Path, default=DEFAULT_CATALOGS_DIR)
    ap.add_argument("--cases", type=Path, default=DEFAULT_CASES_DIR)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--warmup-timeout", type=int, default=600)
    args = ap.parse_args()

    report = asyncio.run(_run(args))
    _print_table(report)
    out = args.out or REPORT_DIR / "retrieve-latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"report: {out}")
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
