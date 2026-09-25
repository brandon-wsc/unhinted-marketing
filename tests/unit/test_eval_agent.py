"""eval_agent report fields + keyless deterministic-only runs (no live keys)."""

from __future__ import annotations

import json

import scripts.eval_agent as EA

_GROUNDING_CASE = """
id: grounding_ok_case
suites: [smoke]
node: grounding_check
db_signal_ids:
  - cassette:ot
state:
  mode: AGENT
  draft:
    caption: 星期五 OT 完飲罐嘢先走。
  source_signal_ids:
    - cassette:ot
expect:
  grounding_ok: true
  kept_signal_ids:
    - cassette:ot
"""

_LLM_CASE = """
id: needs_llm
suites: [smoke]
node: route_intent
state: {}
expect:
  intent: chat
"""


def test_is_deterministic() -> None:
    assert EA._is_deterministic({"node": "grounding_check"}, skip_judge=False)
    assert EA._is_deterministic({"node": "voice_fixture"}, skip_judge=True)
    assert not EA._is_deterministic({"node": "voice_fixture"}, skip_judge=False)
    assert not EA._is_deterministic({"node": "route_intent"}, skip_judge=True)


def test_keyless_run_refuses_llm_cases(tmp_path, monkeypatch, capsys) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "c.yaml").write_text(_LLM_CASE, encoding="utf-8")
    monkeypatch.setattr(EA, "has_llm_credentials", lambda: False)
    assert (
        EA.main(
            [
                "--cases-dir",
                str(cases),
                "--suite",
                "smoke",
                "--out",
                str(tmp_path / "r.json"),
            ]
        )
        == 2
    )
    assert "not set" in capsys.readouterr().err


def test_keyless_run_runs_deterministic_cases(tmp_path, monkeypatch) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "g.yaml").write_text(_GROUNDING_CASE, encoding="utf-8")
    out = tmp_path / "report.json"
    monkeypatch.setattr(EA, "has_llm_credentials", lambda: False)
    assert (
        EA.main(
            [
                "--cases-dir",
                str(cases),
                "--suite",
                "smoke",
                "--skip-judge",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["elapsed_ms"] is not None and report["elapsed_ms"] >= 0
    assert report["models_used"] == []
    assert report["status_counts"] == {}
    row = report["cases"][0]
    assert row["passed"] is True
    assert row["usage"]["calls"] == 0
    assert row["usage"]["status_counts"] == {}
