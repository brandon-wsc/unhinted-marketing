"""thread_recap node (ADR 0057) — deterministic trigger, incremental fold, degrade."""

from __future__ import annotations

import json
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
    # summary_upto=8 already folded; 32 msgs → prefix_len 16 → only msgs[8:16] go in.
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
    # 30 msgs → prefix_len 14, gap 14-8=6 < RECAP_MIN_NEW
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
