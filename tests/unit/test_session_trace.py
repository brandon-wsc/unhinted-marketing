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


def test_clear_and_get_node_trace() -> None:
    with trace.node_trace_recording():
        trace.record_node_step("chat", {"mode": "CHAT"}, {"mode": "CHAT"})
        assert len(trace.get_node_trace()) == 1
        trace.clear_node_trace()
        assert trace.get_node_trace() == []


def test_as_uuid_and_cap_output_branches() -> None:
    assert trace._as_uuid(None) is None
    assert trace._as_uuid("not-a-uuid") is None
    uid = uuid.uuid4()
    assert trace._as_uuid(uid) == uid
    assert trace._cap_output(None) is None
    assert trace._cap_output(3.5) == 3.5
    assert trace._cap_output(object())  # falls back to str
    nested = {"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}}
    assert "max_depth" in str(trace._cap_output(nested))
    long_list = list(range(120))
    capped = trace._cap_output(long_list)
    assert isinstance(capped, list) and len(capped) == 101


@pytest.mark.asyncio
async def test_submit_steps_schedules_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trace.settings, "node_trace_enabled", True)
    persist = AsyncMock()
    monkeypatch.setattr(trace, "_persist_steps_safely", persist)
    turn_id = uuid.uuid4()
    trace.submit_steps(
        turn_id=turn_id,
        session_id=uuid.uuid4(),
        user_id=None,
        company_id=None,
        steps=[trace.NodeStepRecord(node="chat")],
    )
    await trace.drain(timeout=2.0)
    persist.assert_awaited()


@pytest.mark.asyncio
async def test_persist_steps_safely_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(trace, "SessionLocal", lambda: Boom())
    await trace._persist_steps_safely(
        turn_id=uuid.uuid4(),
        session_id=None,
        user_id=None,
        company_id=None,
        steps=[trace.NodeStepRecord(node="chat", output={"x": 1})],
    )
