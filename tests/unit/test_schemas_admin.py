"""Smoke coverage for admin Pydantic shapes (CI schemas gate)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from schemas.admin import (
    LlmCallRecordDetail,
    LlmCallRecordList,
    LlmCallRecordSummary,
    NodeStepDetail,
    NodeStepList,
    NodeStepSummary,
    SessionTrace,
    TraceDraftRevision,
    TraceMessage,
    TraceSignal,
    TraceTurn,
)


def _now() -> datetime:
    return datetime.now(UTC)


def test_llm_call_summary_and_detail_from_attributes() -> None:
    rid = uuid.uuid4()
    row = SimpleNamespace(
        id=rid,
        created_at=_now(),
        caller="node:reviewer",
        node="reviewer",
        session_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        kind="chat_json",
        tier="strong",
        model="gpt-test",
        status="ok",
        latency_ms=10,
        prompt_tokens=1,
        completion_tokens=2,
        total_tokens=3,
        parse_ok=True,
        fallback_used=False,
        key_source="env",
        key_last4="env1",
        user_id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        temperature=0.2,
        system_prompt="sys",
        user_prompt="usr",
        response_text="{}",
        error=None,
    )
    summary = LlmCallRecordSummary.model_validate(row)
    detail = LlmCallRecordDetail.model_validate(row)
    assert summary.id == rid and detail.system_prompt == "sys"
    assert summary.key_source == "env" and summary.key_last4 == "env1"
    listed = LlmCallRecordList(items=[summary], limit=50, offset=0)
    assert listed.limit == 50 and len(listed.items) == 1


def test_node_step_summary_detail_and_list() -> None:
    sid = uuid.uuid4()
    turn = uuid.uuid4()
    row = SimpleNamespace(
        id=sid,
        created_at=_now(),
        session_id=uuid.uuid4(),
        turn_id=turn,
        seq=0,
        node="brainstormer",
        mode_in="AGENT",
        mode_out="AGENT",
        intent_out=None,
        source_signal_ids_in=["a"],
        source_signal_ids_out=["a"],
        output_keys=["brief"],
        user_id=None,
        company_id=None,
        output={"brief": {}},
    )
    summary = NodeStepSummary.model_validate(row)
    detail = NodeStepDetail.model_validate(row)
    detail.llm_calls = []
    assert summary.node == "brainstormer" and detail.output == {"brief": {}}
    assert NodeStepList(items=[summary], limit=10, offset=0).offset == 0


def test_session_trace_payload_assembles() -> None:
    session_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    msg = TraceMessage(
        id=uuid.uuid4(),
        role="user",
        content="hi",
        metadata={"agent_actions": []},
        created_at=_now(),
    )
    draft = TraceDraftRevision(
        id=uuid.uuid4(),
        revision=1,
        draft_copy={"caption": "x"},
        source_signal_ids=["sig-1"],
        created_at=_now(),
    )
    signal = TraceSignal(signal_id="sig-1", source="google_trends", title="T")
    step = NodeStepSummary(
        id=uuid.uuid4(),
        created_at=_now(),
        session_id=session_id,
        turn_id=turn_id,
        seq=0,
        node="chat",
        mode_in="CHAT",
        mode_out="CHAT",
        intent_out=None,
    )
    turn = TraceTurn(turn_id=turn_id, steps=[step], llm_calls=[])
    trace = SessionTrace(
        id=session_id,
        mode="CHAT",
        status="active",
        company_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        created_at=_now(),
        messages=[msg],
        draft_revisions=[draft],
        signals=[signal],
        turns=[turn],
    )
    assert trace.messages[0].content == "hi"
    assert trace.turns[0].steps[0].node == "chat"
    assert trace.signals[0].signal_id == "sig-1"


def test_question_run_summary_defaults() -> None:
    from schemas.admin import QuestionRunList, QuestionRunSummary

    run_id = uuid.uuid4()
    row = SimpleNamespace(
        id=run_id,
        company_id=uuid.uuid4(),
        status="succeeded",
        trigger="get_miss",
        quality_flags=["screen_topup"],
        error=None,
        started_at=_now(),
        finished_at=_now(),
    )
    summary = QuestionRunSummary.model_validate(row)
    assert summary.id == run_id
    assert summary.total_tokens == 0
    listed = QuestionRunList(items=[summary], limit=20)
    assert listed.limit == 20
