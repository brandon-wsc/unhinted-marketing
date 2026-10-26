"""thread_recap node (ADR 0057) — deterministic trigger, incremental fold, degrade."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from internal.session import nodes as N
from internal.session.io import IntentRoute
from internal.session.state import MODE_CHAT


def _msgs(n: int, *, start: int = 0) -> list[dict[str, str]]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i}"}
        for i in range(start, start + n)
    ]


def _state(**extra):
    state = {"mode": MODE_CHAT, "messages": _msgs(1), "draft": {}}
    state.update(extra)
    return state


@pytest.fixture
def llm_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)


@pytest.fixture
def no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: False)


@pytest.mark.asyncio
async def test_recap_noop_under_threshold(llm_ok: None, monkeypatch: pytest.MonkeyPatch) -> None:
    complete = AsyncMock(side_effect=AssertionError("must not call LLM"))
    monkeypatch.setattr(N, "complete_text", complete)
    out = await N.thread_recap(_state(messages=_msgs(N.RECAP_RAW_TAIL + N.RECAP_MIN_NEW - 1)))
    assert out == {}
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_recap_folds_prefix_at_threshold(
    llm_ok: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    async def fake_complete_text(**kwargs):
        captured.update(kwargs)
        return "用戶一路傾緊 Chiikawa 兔糧，跟住想出帖"

    monkeypatch.setattr(N, "complete_text", fake_complete_text)
    msgs = _msgs(N.RECAP_RAW_TAIL + N.RECAP_MIN_NEW)
    out = await N.thread_recap(_state(messages=msgs))

    assert captured["system"] == N.prompts.THREAD_RECAP
    payload = json.loads(captured["user"])
    assert payload["prior_summary"] == ""
    assert payload["new_messages"] == msgs[: N.RECAP_MIN_NEW]
    assert out == {
        "thread_summary": "用戶一路傾緊 Chiikawa 兔糧，跟住想出帖",
        "summary_upto": N.RECAP_MIN_NEW,
    }


@pytest.mark.asyncio
async def test_recap_incremental_slice_only(llm_ok: None, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_complete_text(**kwargs):
        captured.update(kwargs)
        return "updated recap"

    monkeypatch.setattr(N, "complete_text", fake_complete_text)
    # RECAP_MIN_NEW msgs already folded; only the newly-aged slice goes in.
    msgs = _msgs(N.RECAP_RAW_TAIL + 2 * N.RECAP_MIN_NEW)
    out = await N.thread_recap(
        _state(messages=msgs, summary_upto=N.RECAP_MIN_NEW, thread_summary="old recap")
    )
    payload = json.loads(captured["user"])
    assert payload["prior_summary"] == "old recap"
    assert payload["new_messages"] == msgs[N.RECAP_MIN_NEW : 2 * N.RECAP_MIN_NEW]
    assert out["summary_upto"] == 2 * N.RECAP_MIN_NEW


@pytest.mark.asyncio
async def test_recap_waits_for_min_new(llm_ok: None, monkeypatch: pytest.MonkeyPatch) -> None:
    complete = AsyncMock(side_effect=AssertionError("must not call LLM"))
    monkeypatch.setattr(N, "complete_text", complete)
    # Gap since the last fold is 6 < RECAP_MIN_NEW.
    out = await N.thread_recap(
        _state(
            messages=_msgs(N.RECAP_RAW_TAIL + N.RECAP_MIN_NEW + 6),
            summary_upto=N.RECAP_MIN_NEW,
            thread_summary="old recap",
        )
    )
    assert out == {}
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_recap_clamps_stale_summary_upto(
    llm_ok: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    complete = AsyncMock(side_effect=AssertionError("must not call LLM"))
    monkeypatch.setattr(N, "complete_text", complete)
    out = await N.thread_recap(_state(messages=_msgs(30), summary_upto=100, thread_summary="old"))
    assert out == {}
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_recap_llm_error_degrades(llm_ok: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(N, "complete_text", AsyncMock(side_effect=RuntimeError("provider down")))
    out = await N.thread_recap(_state(messages=_msgs(N.RECAP_RAW_TAIL + N.RECAP_MIN_NEW)))
    assert out == {}


@pytest.mark.asyncio
async def test_recap_no_credentials(no_llm: None, monkeypatch: pytest.MonkeyPatch) -> None:
    complete = AsyncMock(side_effect=AssertionError("must not call LLM"))
    monkeypatch.setattr(N, "complete_text", complete)
    out = await N.thread_recap(_state(messages=_msgs(N.RECAP_RAW_TAIL + N.RECAP_MIN_NEW)))
    assert out == {}
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_intent_payload_includes_thread_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    captured: dict[str, str] = {}

    async def fake_complete_json(**kwargs):
        captured["user"] = kwargs["user"]
        return IntentRoute(intent="chat", rationale="x").model_dump_json()

    monkeypatch.setattr(N, "complete_json", fake_complete_json)
    await N.route_intent(
        _state(
            research_rule_pass=True,
            thread_summary="之前傾緊 Chiikawa 兔糧",
            messages=[{"role": "user", "content": "頭先嗰個再講多少少"}],
        )
    )
    payload = json.loads(captured["user"])
    assert payload["thread_summary"] == "之前傾緊 Chiikawa 兔糧"


@pytest.mark.asyncio
async def test_query_generator_payload_includes_thread_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    captured: dict[str, str] = {}

    async def fake_agent(payload, _deps):
        captured["user"] = payload
        return None  # falls through to the fallback path

    monkeypatch.setattr(N.RH, "run_query_generator_agent", fake_agent)
    await N.query_generator(
        _state(
            messages=[
                {"role": "user", "content": "usagi想食嘅兔糧"},
                {"role": "assistant", "content": "你講邊個 Usagi？"},
                {"role": "user", "content": "Chiikawa"},
            ],
            research={"entity_surface": "Chiikawa", "need_facts": True},
            thread_summary="之前研究過兔糧",
        )
    )
    payload = json.loads(captured["user"])
    assert payload["thread_summary"] == "之前研究過兔糧"


@pytest.mark.asyncio
async def test_chat_payload_includes_thread_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    captured: dict[str, str] = {}

    async def fake_stream(*, user_prompt, session_id, deps):
        captured["user"] = user_prompt
        return "收到"

    monkeypatch.setattr(N, "stream_chat_reply", fake_stream)
    out = await N.chat(
        _state(
            messages=[{"role": "user", "content": "頭先嗰個再講吓"}],
            thread_summary="之前傾過出帖",
        )
    )
    payload = json.loads(captured["user"])
    assert payload["thread_summary"] == "之前傾過出帖"
    assert out["messages"][-1]["content"] == "收到"


def test_live_window_is_unsummarized_tail() -> None:
    msgs = _msgs(20)
    state = _state(messages=msgs, summary_upto=8)
    assert N._live_messages(state) == msgs[8:]
    assert N._live_thread(state) == [
        {"role": m["role"], "content": m["content"]} for m in msgs[8:]
    ]


def test_live_window_clamps_stale_summary_upto() -> None:
    msgs = _msgs(20)
    # summary_upto beyond the transcript clamps to prefix_len (len - raw tail).
    state = _state(messages=msgs, summary_upto=100)
    assert N._live_messages(state) == msgs[len(msgs) - N.RECAP_RAW_TAIL :]


def test_live_window_without_summary_is_whole_transcript() -> None:
    msgs = _msgs(10)
    assert N._live_messages(_state(messages=msgs)) == msgs


def test_live_window_capped_when_recap_keeps_failing() -> None:
    msgs = _msgs(60)
    cap = N.RECAP_RAW_TAIL + N.RECAP_MIN_NEW - 1
    assert N._live_messages(_state(messages=msgs)) == msgs[-cap:]


@pytest.mark.asyncio
async def test_route_intent_recent_thread_is_live_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    captured: dict[str, str] = {}

    async def fake_complete_json(**kwargs):
        captured["user"] = kwargs["user"]
        return IntentRoute(intent="chat", rationale="x").model_dump_json()

    monkeypatch.setattr(N, "complete_json", fake_complete_json)
    msgs = _msgs(14)
    await N.route_intent(_state(research_rule_pass=True, messages=msgs))
    payload = json.loads(captured["user"])
    assert payload["recent_thread"] == [
        {"role": m["role"], "content": m["content"]} for m in msgs
    ]


@pytest.mark.asyncio
async def test_chat_history_is_live_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    captured: dict[str, str] = {}

    async def fake_stream(*, user_prompt, session_id, deps):
        captured["user"] = user_prompt
        return "收到"

    monkeypatch.setattr(N, "stream_chat_reply", fake_stream)
    msgs = _msgs(20)
    await N.chat(_state(messages=msgs, summary_upto=8))
    payload = json.loads(captured["user"])
    assert payload["history"] == msgs[8:]


@pytest.mark.asyncio
async def test_query_generator_fallback_hint_stays_last_six(
    no_llm: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    def fake_fallback(entity, user, *, max_len: int = 160):
        captured["entity"] = entity
        captured["hint"] = user
        return ["q-fallback"]

    monkeypatch.setattr(N, "fallback_search_queries", fake_fallback)
    msgs = [
        {"role": "user", "content": "oldest-topic-xyzzy"},
        {"role": "assistant", "content": "ans-0"},
        *_msgs(6, start=10),
    ]
    out = await N.query_generator(
        _state(
            messages=msgs,
            research={"entity_surface": "Chiikawa", "need_facts": True},
        )
    )
    assert out["research"]["query_source"] == N.QUERY_SOURCE_FALLBACK
    assert captured["entity"] == "Chiikawa"
    # The hint joins prior user turns from the last-6 window only.
    assert "oldest-topic-xyzzy" not in captured["hint"]
    assert "msg-10" in captured["hint"]


@pytest.mark.asyncio
async def test_recap_first_fold_capped(llm_ok: None, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_complete_text(**kwargs):
        captured.update(kwargs)
        return "recap"

    monkeypatch.setattr(N, "complete_text", fake_complete_text)
    msgs = _msgs(100)
    out = await N.thread_recap(_state(messages=msgs))
    payload = json.loads(captured["user"])
    prefix_len = len(msgs) - N.RECAP_RAW_TAIL  # 92
    assert payload["new_messages"] == msgs[prefix_len - N.RECAP_MAX_FOLD : prefix_len]
    assert out["summary_upto"] == prefix_len


def test_thread_recap_edges() -> None:
    from internal.session.graph import build_session_graph

    edges = {(e.source, e.target) for e in build_session_graph().get_graph().edges}
    assert ("fast_rule_checker", "thread_recap") in edges
    assert ("thread_recap", "route_intent") in edges
    assert ("fast_rule_checker", "route_intent") not in edges


def test_graph_values_carries_recap_pair() -> None:
    from internal.session.service import _graph_values

    session = SimpleNamespace(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        mode=MODE_CHAT,
        state={"thread_summary": "recap text", "summary_upto": 8},
    )
    vals = _graph_values(session, [])
    assert vals["thread_summary"] == "recap text"
    assert vals["summary_upto"] == 8

    session.state = {}
    vals = _graph_values(session, [])
    assert vals["thread_summary"] == ""
    assert vals["summary_upto"] == 0
