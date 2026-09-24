"""Diff a committed eval baseline against the latest eval report.

Not a PR gate — a local before/after tool for prompt/node work.

Usage (repo root, after `python -m scripts.eval_agent`):

    python -m scripts.eval_diff                      # baseline vs latest
    python -m scripts.eval_diff --latest other.json
    python -m scripts.eval_diff --accept             # latest -> baseline.json

Regression thresholds (defaults; each flag overrides):

    * any case that passed in baseline and fails now    -> fail
    * mean_voice drop  > --max-voice-drop   (0.05)      -> fail
    * p95_ms           > --max-p95-ratio x baseline (1.5)
                       AND > --max-p95-abs-ms over (+500) -> fail
    * total_tokens     > --max-token-ratio x baseline (1.5) -> fail

Exit codes: 0 ok / 1 regression / 2 missing or invalid files.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO_ROOT / "reports" / "eval" / "baseline.json"
DEFAULT_LATEST = REPO_ROOT / "reports" / "eval" / "latest.json"


def _load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"eval_diff: {path} not found", file=sys.stderr)
        return None
    except json.JSONDecodeError as exc:
        print(f"eval_diff: {path} is not valid JSON: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict) or "cases" not in data:
        print(f"eval_diff: {path} does not look like an eval report", file=sys.stderr)
        return None
    return data


def _cases_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(c.get("id")): c for c in report.get("cases") or [] if c.get("id")}


def _num(report: dict[str, Any], key: str) -> float | None:
    value = report.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def compute_deltas(
    baseline: dict[str, Any], latest: dict[str, Any]
) -> dict[str, Any]:
    """Metric deltas + per-case flips between two eval report dicts."""
    base_cases = _cases_by_id(baseline)
    new_cases = _cases_by_id(latest)
    regressions = sorted(
        cid
        for cid, base in base_cases.items()
        if base.get("passed") and not (new_cases.get(cid) or {}).get("passed", True)
    )
    fixed = sorted(
        cid
        for cid, base in base_cases.items()
        if not base.get("passed") and (new_cases.get(cid) or {}).get("passed", False)
    )
    added = sorted(cid for cid in new_cases if cid not in base_cases)
    dropped = sorted(cid for cid in base_cases if cid not in new_cases)
    metrics: dict[str, dict[str, Any]] = {}
    for key in (
        "pass_rate",
        "mean_voice",
        "p50_ms",
        "p95_ms",
        "total_tokens",
        "total_usd",
    ):
        before = _num(baseline, key)
        after = _num(latest, key)
        metrics[key] = {
            "baseline": before,
            "latest": after,
            "delta": (after - before) if (before is not None and after is not None) else None,
        }
    metrics["passed"] = {
        "baseline": baseline.get("passed"),
        "latest": latest.get("passed"),
        "delta": (latest.get("passed") or 0) - (baseline.get("passed") or 0),
    }
    return {
        "metrics": metrics,
        "regressions": regressions,
        "fixed": fixed,
        "added": added,
        "dropped": dropped,
    }


def check_regressions(
    deltas: dict[str, Any],
    *,
    max_voice_drop: float,
    max_p95_ratio: float,
    max_p95_abs_ms: int,
    max_token_ratio: float,
) -> list[str]:
    """Human-readable failure lines; empty list = no regression."""
    failures: list[str] = []
    for cid in deltas["regressions"]:
        failures.append(f"case {cid!r} passed in baseline, fails now")
    voice = deltas["metrics"]["mean_voice"]
    if voice["delta"] is not None and voice["delta"] < -max_voice_drop:
        failures.append(
            f"mean_voice dropped {voice['delta']:+.3f} (allowed -{max_voice_drop})"
        )
    p95 = deltas["metrics"]["p95_ms"]
    if (
        p95["baseline"]
        and p95["latest"] is not None
        and p95["latest"] > p95["baseline"] * max_p95_ratio
        and p95["latest"] - p95["baseline"] > max_p95_abs_ms
    ):
        failures.append(
            f"p95_ms {p95['baseline']:.0f} -> {p95['latest']:.0f}"
            f" (>{max_p95_ratio}x and >+{max_p95_abs_ms}ms)"
        )
    toks = deltas["metrics"]["total_tokens"]
    if (
        toks["baseline"]
        and toks["latest"] is not None
        and toks["latest"] > toks["baseline"] * max_token_ratio
    ):
        failures.append(
            f"total_tokens {toks['baseline']:.0f} -> {toks['latest']:.0f}"
            f" (>{max_token_ratio}x)"
        )
    return failures


def _fmt(value: Any, *, money: bool = False) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"${value:.4f}" if money else f"{value:.3f}"
    return str(value)


def _print(deltas: dict[str, Any], failures: list[str]) -> None:
    print(f"{'metric':<14} {'baseline':>10} {'latest':>10} {'delta':>10}")
    print("-" * 48)
    for key, row in deltas["metrics"].items():
        money = key == "total_usd"
        print(
            f"{key:<14} {_fmt(row['baseline'], money=money):>10}"
            f" {_fmt(row['latest'], money=money):>10}"
            f" {_fmt(round(row['delta'], 4) if isinstance(row['delta'], float) else row['delta'], money=money):>10}"
        )
    for label in ("regressions", "fixed", "added", "dropped"):
        ids = deltas[label]
        if ids:
            print(f"\n{label}: {', '.join(ids)}")
    print()
    if failures:
        print("REGRESSION:")
        for line in failures:
            print(f"  - {line}")
    else:
        print("no regression past thresholds")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diff committed baseline.json vs latest.json eval reports",
        epilog="Defaults: voice drop 0.05, p95 1.5x & +500ms, tokens 1.5x;"
        " any pass->fail case is always a regression.",
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--latest", type=Path, default=DEFAULT_LATEST)
    parser.add_argument("--max-voice-drop", type=float, default=0.05)
    parser.add_argument("--max-p95-ratio", type=float, default=1.5)
    parser.add_argument("--max-p95-abs-ms", type=int, default=500)
    parser.add_argument("--max-token-ratio", type=float, default=1.5)
    parser.add_argument(
        "--allow-case-flips",
        action="store_true",
        help="Do not fail on pass->fail case flips (metric thresholds still apply)",
    )
    parser.add_argument(
        "--accept",
        action="store_true",
        help="Copy --latest over --baseline (accept current run as the new anchor)",
    )
    args = parser.parse_args(argv)

    if args.accept:
        if not args.latest.exists():
            print(f"eval_diff: {args.latest} not found", file=sys.stderr)
            return 2
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.latest, args.baseline)
        print(f"baseline updated: {args.baseline}")
        return 0

    baseline = _load(args.baseline)
    latest = _load(args.latest)
    if baseline is None or latest is None:
        return 2
    deltas = compute_deltas(baseline, latest)
    if args.allow_case_flips:
        deltas["regressions"] = []
    failures = check_regressions(
        deltas,
        max_voice_drop=args.max_voice_drop,
        max_p95_ratio=args.max_p95_ratio,
        max_p95_abs_ms=args.max_p95_abs_ms,
        max_token_ratio=args.max_token_ratio,
    )
    _print(deltas, failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
