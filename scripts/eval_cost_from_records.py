"""Cost/latency surface over prod ``llm_call_records`` (ADR 0005).

Read-only. Answers "what is the p95 and rough $ of my LLM loop" without a
dashboard. Uses the same static price table as the eval pack
(``internal/llm/pricing.py``) — unknown models show ``usd —``, never invented.

Usage (repo root, DATABASE_URL pointing at a dev/prod copy):

    python -m scripts.eval_cost_from_records              # last 7 days
    python -m scripts.eval_cost_from_records --days 30
    python -m scripts.eval_cost_from_records --node executor_post
    python -m scripts.eval_cost_from_records --kind image --days 1
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from internal.llm.pricing import normalize_model_id, usd_for
from internal.memory.database import SessionLocal
from internal.memory.models import LlmCallRecord


def _percentile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[idx]


def _fmt_ms(value: int | None) -> str:
    return f"{value}ms" if value is not None else "—"


def _fmt_usd(value: float | None) -> str:
    return f"${value:.4f}" if value is not None else "—"


async def _collect(args: argparse.Namespace) -> dict[str, Any] | None:
    since = datetime.now(UTC) - timedelta(days=args.days)
    stmt = select(LlmCallRecord).where(LlmCallRecord.created_at >= since)
    if args.node:
        stmt = stmt.where(LlmCallRecord.node == args.node)
    if args.caller:
        stmt = stmt.where(LlmCallRecord.caller == args.caller)
    if args.kind:
        stmt = stmt.where(LlmCallRecord.kind == args.kind)
    async with SessionLocal() as db:
        rows = (await db.scalars(stmt)).all()
    if not rows:
        return None

    latencies = [r.latency_ms for r in rows if r.latency_ms is not None]
    prompt = sum(r.prompt_tokens or 0 for r in rows)
    completion = sum(r.completion_tokens or 0 for r in rows)
    total = sum(r.total_tokens or 0 for r in rows)
    usd = 0.0
    unknown: list[str] = []
    for r in rows:
        call_usd = usd_for(r.model, r.prompt_tokens, r.completion_tokens)
        if call_usd is not None:
            usd += call_usd
        elif (r.prompt_tokens or r.completion_tokens) and r.model:
            leaf = normalize_model_id(r.model)
            if leaf not in unknown:
                unknown.append(leaf)
    per_model: dict[str, dict[str, Any]] = {}
    for r in rows:
        leaf = normalize_model_id(r.model) or "unknown"
        bucket = per_model.setdefault(
            leaf, {"calls": 0, "latency_ms": [], "total_tokens": 0, "usd": 0.0}
        )
        bucket["calls"] += 1
        if r.latency_ms is not None:
            bucket["latency_ms"].append(r.latency_ms)
        bucket["total_tokens"] += r.total_tokens or 0
        call_usd = usd_for(r.model, r.prompt_tokens, r.completion_tokens)
        if call_usd is not None:
            bucket["usd"] += call_usd
    return {
        "calls": len(rows),
        "p50_ms": _percentile(latencies, 0.5),
        "p95_ms": _percentile(latencies, 0.95),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "usd": round(usd, 6) if not unknown else None,
        "unknown_models": unknown,
        "per_model": per_model,
        "since": since,
    }


def _print(summary: dict[str, Any], *, days: int) -> None:
    print(
        f"llm_call_records last {days}d — {summary['calls']} calls "
        f"(since {summary['since'].date()})"
    )
    print("-" * 78)
    print(
        f"latency p50 {_fmt_ms(summary['p50_ms'])}"
        f"  p95 {_fmt_ms(summary['p95_ms'])}"
        f"  tokens {summary['total_tokens']}"
        f" ({summary['prompt_tokens']} in / {summary['completion_tokens']} out)"
        f"  usd {_fmt_usd(summary['usd'])}"
    )
    if summary["unknown_models"]:
        print(f"unpriced models: {', '.join(summary['unknown_models'])}")
    print()
    print(f"{'model':<36} {'calls':>6} {'p50':>8} {'p95':>8} {'tokens':>10} {'usd':>10}")
    print("-" * 78)
    for model, bucket in sorted(
        summary["per_model"].items(), key=lambda kv: -kv[1]["calls"]
    ):
        print(
            f"{model:<36} {bucket['calls']:>6}"
            f" {_fmt_ms(_percentile(bucket['latency_ms'], 0.5)):>8}"
            f" {_fmt_ms(_percentile(bucket['latency_ms'], 0.95)):>8}"
            f" {bucket['total_tokens']:>10} {_fmt_usd(bucket['usd'] or None):>10}"
        )


async def _run(args: argparse.Namespace) -> int:
    try:
        summary = await _collect(args)
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(
            f"eval_cost_from_records: could not query llm_call_records "
            f"({type(exc).__name__}: {exc}). Check DATABASE_URL / migrations.",
            file=sys.stderr,
        )
        return 2
    if summary is None:
        print(
            f"no llm_call_records in the last {args.days} day(s) "
            "— is LLM_RECORD_ENABLED on and has the app served traffic?"
        )
        return 0
    _print(summary, days=args.days)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="p50/p95 latency, tokens, and rough USD from llm_call_records",
    )
    parser.add_argument("--days", type=int, default=7, help="look-back window")
    parser.add_argument("--node", type=str, default=None, help="filter by node")
    parser.add_argument("--caller", type=str, default=None, help="filter by caller")
    parser.add_argument(
        "--kind",
        type=str,
        default=None,
        choices=["chat_json", "chat_text", "image"],
        help="filter by call kind",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
