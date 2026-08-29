"""On-demand live-LLM eval of session harness nodes.

Not a PR gate. Same command for humans and coding agents.

Usage (repo root, after `pip install -e ".[dev]"` and OPENAI_API_KEY in .env):

    python -m scripts.eval_agent
    python -m scripts.eval_agent --suite smoke
    python -m scripts.eval_agent --suite research
    python -m scripts.eval_agent --suite all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from internal.config import settings
from internal.llm.router import LlmProviderError, has_llm_credentials
from internal.session import execute_harness as EH
from internal.session import ingest as ingest_mod
from internal.session import nodes as N
from internal.session.context import session_db
from schemas.tools import QueryMarketTrendsResponse, QueryMarketTrendsSignal
from tests.eval.graders import grade_case

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_DIR = REPO_ROOT / "tests" / "eval" / "cases"
DEFAULT_CASSETTE = REPO_ROOT / "tests" / "eval" / "cassettes" / "signals.json"
REPORT_DIR = REPO_ROOT / "reports" / "eval"
SUITES = ("smoke", "research", "all")


def _silence_recording() -> None:
    os.environ["LLM_RECORD_ENABLED"] = "false"
    os.environ["NODE_TRACE_ENABLED"] = "false"
    settings.llm_record_enabled = False
    settings.node_trace_enabled = False
    settings.semantic_router_enabled = False


def _load_cassette(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("signals") or [])


def _load_cases(cases_dir: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(cases_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if data is None:
            continue
        if isinstance(data, list):
            cases.extend(data)
        else:
            cases.append(data)
    return cases


def _in_suite(case: dict[str, Any], suite: str) -> bool:
    listed = case.get("suites") or []
    if suite == "all":
        return True
    return suite in listed


def _signal_response(signals: list[dict[str, Any]], region: str) -> QueryMarketTrendsResponse:
    rows = [
        QueryMarketTrendsSignal(
            signal_id=str(item.get("signal_id") or ""),
            source=str(item.get("source") or "cassette"),
            title=str(item.get("title") or ""),
            url=item.get("url"),
            excerpt=item.get("excerpt"),
            region=item.get("region") or region,
            metrics=dict(item.get("metrics") or {}),
        )
        for item in signals
        if item.get("signal_id")
    ]
    return QueryMarketTrendsResponse(
        region=region,
        signals=rows,
        ranked_signal_ids=[r.signal_id for r in rows],
        notes="eval cassette",
    )


@contextmanager
def _tool_stubs(signals: list[dict[str, Any]]) -> Iterator[None]:
    async def fake_fetch(
        _db: AsyncSession,
        queries: list[str],
        **_kwargs: object,
    ) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        for query in queries:
            for item in signals:
                metrics = dict(item.get("metrics") or {})
                metrics["query"] = query
                hits.append({**item, "metrics": metrics})
        return hits

    async def fake_lookup(region: str = "HK", limit: int = 20) -> QueryMarketTrendsResponse:
        del limit
        return _signal_response(signals, region)

    with (
        patch.object(ingest_mod, "fetch_and_upsert_tavily", fake_fetch),
        patch.object(N, "has_llm_credentials", lambda: True),
        patch("internal.session.harness.lookup_market_trends", fake_lookup),
        session_db(AsyncMock()),
    ):
        yield


async def _run_query_generator(state: dict[str, Any]) -> dict[str, Any]:
    out = await N.query_generator(state)
    return dict(out)


async def _run_route_intent(state: dict[str, Any]) -> dict[str, Any]:
    parsed_ok = False
    orig = N._parse_llm_json

    async def _spy(*args: Any, **kwargs: Any) -> Any:
        nonlocal parsed_ok
        result = await orig(*args, **kwargs)
        parsed_ok = result is not None
        return result

    with patch.object(N, "_parse_llm_json", _spy):
        out = await N.route_intent(state)
    payload = dict(out)
    payload["_eval_parse_ok"] = parsed_ok
    return payload


async def _run_executor_post(state: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "company": N._slim_company(state),
        "voice_pack": N._voice_pack(state),
        "active_persona": state.get("active_persona"),
        "brief": state.get("brief") or {},
        "signals": N._ranked_signals(state)[:8],
        "signals_trusted": True,
        "allowed_signal_ids": list(state.get("source_signal_ids") or []),
        "user_request": N._last_user_text(state),
        "primary_product": state.get("primary_product"),
        "related_products": (state.get("related_products") or [])[:2],
    }
    parsed = await EH.run_executor_post_agent(
        json.dumps(payload, ensure_ascii=False),
        EH.ExecuteDeps(),
    )
    return {"parsed": parsed.model_dump() if parsed else None}


async def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    node = case.get("node")
    state = dict(case.get("state") or {})
    if node == "query_generator":
        return await _run_query_generator(state)
    if node == "route_intent":
        return await _run_route_intent(state)
    if node == "executor_post":
        return await _run_executor_post(state)
    raise ValueError(f"unknown node {node!r}")


def _summarize_output(node: str, output: dict[str, Any]) -> dict[str, Any]:
    if node == "query_generator":
        research = output.get("research") or {}
        return {
            "search_query": output.get("search_query"),
            "search_queries": research.get("search_queries"),
            "query_source": research.get("query_source"),
        }
    if node == "route_intent":
        return {
            "intent": output.get("intent"),
            "parse_ok": output.get("_eval_parse_ok"),
        }
    if node == "executor_post":
        parsed = output.get("parsed") or {}
        caption = str(parsed.get("caption") or "")
        return {
            "caption": caption[:500],
            "hashtags": parsed.get("hashtags"),
            "cta": parsed.get("cta"),
        }
    return output


def _write_reports(report: dict[str, Any]) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / "latest.json"
    md_path = REPORT_DIR / "latest.md"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"# Agent eval — `{report['suite']}`",
        "",
        f"- when: {report['when']}",
        f"- ok: **{report['ok']}**",
        f"- cases: {report['passed']}/{report['total']} passed",
        "",
        "| id | node | pass | reason |",
        "|---|---|---|---|",
    ]
    for row in report["cases"]:
        reason = "; ".join(row["reasons"]) if row["reasons"] else ""
        mark = "yes" if row["passed"] else "no"
        lines.append(f"| `{row['id']}` | {row['node']} | {mark} | {reason} |")
        if row.get("output"):
            lines.append("")
            lines.append(f"### `{row['id']}` output")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(row["output"], indent=2, ensure_ascii=False))
            lines.append("```")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def _print_table(rows: list[dict[str, Any]]) -> None:
    print(f"{'id':<32} {'node':<18} {'pass':<6} reason")
    print("-" * 88)
    for row in rows:
        reason = "; ".join(row["reasons"]) if row["reasons"] else ""
        mark = "ok" if row["passed"] else "FAIL"
        print(f"{row['id']:<32} {row['node']:<18} {mark:<6} {reason}")


async def _eval_suite(suite: str, cases_dir: Path, cassette_path: Path) -> dict[str, Any]:
    _silence_recording()
    signals = _load_cassette(cassette_path)
    selected = [c for c in _load_cases(cases_dir) if _in_suite(c, suite)]
    if not selected:
        raise SystemExit(f"no cases for suite {suite!r} in {cases_dir}")

    rows: list[dict[str, Any]] = []
    with _tool_stubs(signals):
        for case in selected:
            cid = str(case.get("id") or "unnamed")
            node = str(case.get("node") or "")
            try:
                output = await _run_case(case)
                reasons = grade_case(case, output)
            except LlmProviderError as exc:
                output = {}
                reasons = [f"provider: {exc}"]
            except Exception as exc:  # noqa: BLE001 — per-case isolation
                output = {}
                reasons = [f"{type(exc).__name__}: {exc}"]
            rows.append(
                {
                    "id": cid,
                    "suites": list(case.get("suites") or []),
                    "node": node,
                    "passed": not reasons,
                    "reasons": reasons,
                    "output": _summarize_output(node, output),
                }
            )

    passed = sum(1 for r in rows if r["passed"])
    return {
        "suite": suite,
        "when": datetime.now(UTC).isoformat(),
        "ok": passed == len(rows),
        "passed": passed,
        "total": len(rows),
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live-LLM eval of session harness nodes")
    parser.add_argument(
        "--suite",
        choices=SUITES,
        default="smoke",
        help="Case pack to run (default: smoke)",
    )
    parser.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_DIR)
    parser.add_argument("--cassette", type=Path, default=DEFAULT_CASSETTE)
    args = parser.parse_args(argv)

    _silence_recording()
    if not has_llm_credentials():
        print(
            "eval_agent: OPENAI_API_KEY or ANTHROPIC_API_KEY is not set "
            "(see .env). Refusing to skip.",
            file=sys.stderr,
        )
        return 2

    report = asyncio.run(_eval_suite(args.suite, args.cases_dir, args.cassette))
    json_path, md_path = _write_reports(report)
    _print_table(report["cases"])
    print()
    print(f"wrote {md_path.relative_to(REPO_ROOT)}")
    print(f"wrote {json_path.relative_to(REPO_ROOT)}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
