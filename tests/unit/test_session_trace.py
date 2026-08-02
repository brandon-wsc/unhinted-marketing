"""Node-step turn_trace + output capping."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from internal.session import trace


def test_record_node_step_noop_without_context() -> None:
    assert trace.record_node_step("chat", {"mode": "CHAT"}, {"mode": "CHAT"}) is None


def test_node_trace_recording_collects_steps() -> None:
    with trace.node_trace_recording() as steps:
        trace.record_node_step(
            "route_intent",
            {"mode": "CHAT", "source_signal_ids": ["a"]},
            {"intent": "start", "mode": "AGENT", "source_signal_ids": ["a", "b"]},
        )
        assert len(steps) == 1
        assert steps[0].node == "route_intent"
        assert steps[0].intent_out == "start"
        assert steps[0].source_signal_ids_out == ["a", "b"]


def test_turn_trace_sets_current_turn_id_and_submits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trace.settings, "node_trace_enabled", True)
    submitted: list = []

    def fake_submit(**kwargs) -> None:
        submitted.append(kwargs)

    monkeypatch.setattr(trace, "submit_steps", fake_submit)
    session_id = uuid.uuid4()
    with trace.turn_trace(session_id=session_id, user_id=uuid.uuid4()) as tid:
        assert trace.current_turn_id() == tid
        trace.record_node_step("load_context", {"mode": "AGENT"}, {"profile": {}})
    assert trace.current_turn_id() is None
    assert len(submitted) == 1
    assert submitted[0]["turn_id"] == tid
    assert submitted[0]["session_id"] == session_id
    assert len(submitted[0]["steps"]) == 1


def test_cap_output_truncates_data_uri_and_long_strings() -> None:
    data = "data:image/png;base64," + ("x" * 100)
    out = trace._cap_output({"img": data, "ok": True, "big": "y" * 25_000})
    assert out["ok"] is True
    assert out["img"].startswith("data:image/png;base64,<")
    assert out["big"].endswith("chars]")


@pytest.mark.asyncio
async def test_submit_steps_disabled_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trace.settings, "node_trace_enabled", False)
    with patch.object(trace, "_persist_steps_safely", new_callable=AsyncMock) as persist:
        trace.submit_steps(
            turn_id=uuid.uuid4(),
            session_id=None,
            user_id=None,
            company_id=None,
            steps=[trace.NodeStepRecord(node="chat")],
        )
        persist.assert_not_called()
