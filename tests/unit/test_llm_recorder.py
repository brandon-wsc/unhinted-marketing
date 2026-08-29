"""LLM call recorder — track/context/mark/submit behavior (ADR 0005, no DB)."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from internal.config import settings
from internal.llm import recorder
from internal.llm.router import LlmProviderError


@pytest.fixture
def collected(monkeypatch: pytest.MonkeyPatch) -> list:
    sent: list[recorder.LlmCallRecordBuilder] = []
    monkeypatch.setattr(recorder, "submit", sent.append)
    return sent


async def test_track_ok_buffers_in_context_and_flushes_on_exit(collected: list) -> None:
    sid = uuid.uuid4()
    uid = uuid.uuid4()
    cid = uuid.uuid4()
    with recorder.call_context(
        caller="node:reviewer", node="reviewer",
        session_id=str(sid), user_id=str(uid), company_id=str(cid),
    ):
        with recorder.track(kind="chat_json", tier="strong", model="gpt-test", temperature=0.4,
                            system="sys", user="usr") as rec:
            rec.response_text = '{"passed": true}'
        assert collected == []  # still buffered until the context exits

    assert len(collected) == 1
    rec = collected[0]
    assert rec.status == "ok"
    assert rec.caller == "node:reviewer"
    assert rec.node == "reviewer"
    assert (rec.session_id, rec.user_id, rec.company_id) == (sid, uid, cid)
    assert rec.latency_ms is not None and rec.latency_ms >= 0
    assert rec.response_text == '{"passed": true}'


async def test_track_without_context_submits_immediately(collected: list) -> None:
    with recorder.track(kind="chat_text", model="gpt-test"):
        pass
    assert len(collected) == 1
    assert collected[0].status == "ok"


async def test_track_classifies_provider_error(collected: list) -> None:
    with (
        pytest.raises(LlmProviderError),
        recorder.track(kind="chat_json", model="gpt-test"),
    ):
        raise LlmProviderError("timed out", model="gpt-test", kind="timeout")
    rec = collected[0]
    assert rec.status == "provider_error"
    assert rec.error == {"error": "timed out", "kind": "timeout", "model": "gpt-test"}


async def test_track_classifies_cancelled(collected: list) -> None:
    with (
        pytest.raises(asyncio.CancelledError),
        recorder.track(kind="chat_text", model="gpt-test"),
    ):
        raise asyncio.CancelledError()
    assert collected[0].status == "cancelled"


async def test_track_classifies_unexpected_error(collected: list) -> None:
    with (
        pytest.raises(ValueError),
        recorder.track(kind="chat_json", model="gpt-test"),
    ):
        raise ValueError("boom")
    rec = collected[0]
    assert rec.status == "error"
    assert rec.error["kind"] == "internal"
    assert "boom" in rec.error["message"]


async def test_track_keeps_pre_marked_status(collected: list) -> None:
    with (
        pytest.raises(RuntimeError),
        recorder.track(kind="chat_json", model="gpt-test") as rec,
    ):
        rec.fail("empty_response", {"kind": "empty_response", "message": "empty"})
        raise RuntimeError("LLM returned empty content")
    rec = collected[0]
    assert rec.status == "empty_response"
    assert rec.error["kind"] == "empty_response"


async def test_mark_last_call_sets_parse_and_fallback(collected: list) -> None:
    with recorder.call_context(caller="node:route_intent", node="route_intent"):
        with recorder.track(kind="chat_json", model="gpt-test"):
            pass
        recorder.mark_last_call(parse_ok=False, fallback_used=True)
    rec = collected[0]
    assert rec.parse_ok is False
    assert rec.fallback_used is True


async def test_mark_last_call_without_context_is_noop() -> None:
    recorder.mark_last_call(parse_ok=True, fallback_used=True)  # must not raise


async def test_mark_last_call_parse_ok_true(collected: list) -> None:
    with recorder.call_context(caller="node:reviewer", node="reviewer"):
        with recorder.track(kind="chat_json", model="gpt-test"):
            pass
        recorder.mark_last_call(parse_ok=True)
    assert collected[0].parse_ok is True


async def test_context_parses_uuid_strings_and_ignores_bad(collected: list) -> None:
    with (
        recorder.call_context(caller="node:chat", node="chat", session_id="not-a-uuid"),
        recorder.track(kind="chat_text", model="gpt-test"),
    ):
        pass
    assert collected[0].session_id is None


async def test_flush_order_matches_call_order(collected: list) -> None:
    with recorder.call_context(caller="node:chat", node="chat"):
        with recorder.track(kind="chat_text", model="m1") as rec:
            rec.response_text = "first"
        with recorder.track(kind="chat_text", model="m2") as rec:
            rec.response_text = "second"
    assert [r.response_text for r in collected] == ["first", "second"]


def test_set_usage_from_object_and_dict() -> None:
    rec = recorder.LlmCallRecordBuilder(kind="chat_json")
    rec.set_usage(SimpleNamespace(prompt_tokens=3, completion_tokens=5, total_tokens=8))
    assert (rec.prompt_tokens, rec.completion_tokens, rec.total_tokens) == (3, 5, 8)

    rec2 = recorder.LlmCallRecordBuilder(kind="chat_json")
    rec2.set_usage({"prompt_tokens": 10, "completion_tokens": 4})
    assert rec2.total_tokens == 14  # summed when total missing

    rec3 = recorder.LlmCallRecordBuilder(kind="chat_json")
    rec3.set_usage(SimpleNamespace(input_tokens=7, output_tokens=2))
    assert (rec3.prompt_tokens, rec3.completion_tokens, rec3.total_tokens) == (7, 2, 9)

    rec4 = recorder.LlmCallRecordBuilder(kind="chat_json")
    rec4.set_usage(None)
    assert rec4.total_tokens is None


def test_to_model_caps_long_text() -> None:
    rec = recorder.LlmCallRecordBuilder(
        kind="chat_json", caller="node:x", system_prompt="x" * 60_000
    )
    model = rec.to_model()
    assert len(model.system_prompt) < 60_000
    assert model.system_prompt.endswith("chars]")


def test_to_model_summarizes_image_data_uri() -> None:
    rec = recorder.LlmCallRecordBuilder(kind="image", caller="node:executor_image_gen")
    rec.response_text = "data:image/png;base64," + "A" * 100
    model = rec.to_model()
    assert model.response_text == "data:image/png;base64,<122 chars>"


def test_to_model_defaults_unknown_caller() -> None:
    model = recorder.LlmCallRecordBuilder(kind="chat_json").to_model()
    assert model.caller == "unknown"


async def test_submit_persists_via_background_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_record_enabled", True)
    persisted: list = []

    async def fake_persist(rec: recorder.LlmCallRecordBuilder) -> None:
        persisted.append(rec)

    monkeypatch.setattr(recorder, "_persist_safely", fake_persist)
    recorder.submit(recorder.LlmCallRecordBuilder(kind="chat_json", caller="node:x"))
    await recorder.drain()
    assert len(persisted) == 1


async def test_submit_disabled_drops(monkeypatch: pytest.MonkeyPatch) -> None:
    # Global conftest sets llm_record_enabled=False.
    persisted: list = []

    async def fake_persist(rec: recorder.LlmCallRecordBuilder) -> None:
        persisted.append(rec)

    monkeypatch.setattr(recorder, "_persist_safely", fake_persist)
    recorder.submit(recorder.LlmCallRecordBuilder(kind="chat_json", caller="node:x"))
    await recorder.drain()
    assert persisted == []
