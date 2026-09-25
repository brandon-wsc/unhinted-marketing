"""eval_diff delta math + thresholds — pure dicts, no live keys."""

from __future__ import annotations

import json

from scripts.eval_diff import check_regressions, compute_deltas, main

_THRESHOLDS = {
    "max_voice_drop": 0.05,
    "max_p95_ratio": 1.5,
    "max_p95_abs_ms": 500,
    "max_token_ratio": 1.5,
}


def _report(cases: dict[str, bool], **metrics: float | int | None) -> dict:
    return {
        "passed": sum(1 for ok in cases.values() if ok),
        "total": len(cases),
        "cases": [{"id": cid, "passed": ok} for cid, ok in cases.items()],
        **metrics,
    }


def test_identical_reports_no_regression() -> None:
    report = _report(
        {"a": True, "b": True},
        pass_rate=1.0,
        mean_voice=0.7,
        p95_ms=4000,
        total_tokens=12000,
    )
    deltas = compute_deltas(report, report)
    assert deltas["regressions"] == []
    assert check_regressions(deltas, **_THRESHOLDS) == []


def test_pass_to_fail_case_is_regression() -> None:
    baseline = _report({"a": True, "b": True}, pass_rate=1.0)
    latest = _report({"a": True, "b": False}, pass_rate=0.5)
    deltas = compute_deltas(baseline, latest)
    failures = check_regressions(deltas, **_THRESHOLDS)
    assert any("'b'" in line for line in failures)


def test_fail_to_pass_case_is_fixed_not_regression() -> None:
    baseline = _report({"a": False}, pass_rate=0.0)
    latest = _report({"a": True}, pass_rate=1.0)
    deltas = compute_deltas(baseline, latest)
    assert deltas["fixed"] == ["a"]
    assert check_regressions(deltas, **_THRESHOLDS) == []


def test_added_and_dropped_cases_listed() -> None:
    baseline = _report({"a": True, "b": True})
    latest = _report({"a": True, "c": True})
    deltas = compute_deltas(baseline, latest)
    assert deltas["added"] == ["c"]
    assert deltas["dropped"] == ["b"]
    assert deltas["regressions"] == []


def test_voice_drop_beyond_threshold_fails() -> None:
    baseline = _report({"a": True}, mean_voice=0.70)
    small = _report({"a": True}, mean_voice=0.66)
    big = _report({"a": True}, mean_voice=0.60)
    assert check_regressions(compute_deltas(baseline, small), **_THRESHOLDS) == []
    failures = check_regressions(compute_deltas(baseline, big), **_THRESHOLDS)
    assert any("mean_voice" in line for line in failures)


def test_p95_needs_ratio_and_absolute() -> None:
    baseline = _report({"a": True}, p95_ms=100)
    latest = _report({"a": True}, p95_ms=550)  # 5.5x but only +450ms
    assert check_regressions(compute_deltas(baseline, latest), **_THRESHOLDS) == []
    baseline2 = _report({"a": True}, p95_ms=4000)
    latest2 = _report({"a": True}, p95_ms=7000)  # 1.75x and +3000ms
    failures = check_regressions(compute_deltas(baseline2, latest2), **_THRESHOLDS)
    assert any("p95_ms" in line for line in failures)


def test_token_spike_fails() -> None:
    baseline = _report({"a": True}, total_tokens=10000)
    latest = _report({"a": True}, total_tokens=20000)
    failures = check_regressions(compute_deltas(baseline, latest), **_THRESHOLDS)
    assert any("total_tokens" in line for line in failures)


def test_missing_latest_exits_2(tmp_path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(_report({"a": True})), encoding="utf-8")
    assert (
        main(["--baseline", str(baseline), "--latest", str(tmp_path / "nope.json")])
        == 2
    )


def test_accept_copies_latest(tmp_path) -> None:
    baseline = tmp_path / "baseline.json"
    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps(_report({"a": True})), encoding="utf-8")
    assert main(["--baseline", str(baseline), "--latest", str(latest), "--accept"]) == 0
    assert json.loads(baseline.read_text(encoding="utf-8"))["total"] == 1


def test_main_returns_1_on_regression(tmp_path) -> None:
    baseline = tmp_path / "baseline.json"
    latest = tmp_path / "latest.json"
    baseline.write_text(json.dumps(_report({"a": True})), encoding="utf-8")
    latest.write_text(json.dumps(_report({"a": False})), encoding="utf-8")
    assert main(["--baseline", str(baseline), "--latest", str(latest)]) == 1
