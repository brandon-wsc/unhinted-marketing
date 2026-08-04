"""Session LangGraph nodes with mocked LLM / repos — no live API, no Postgres."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from internal.session import nodes as N
from internal.session.context import session_db
from internal.session.io import BriefOut, DraftOut, IntentRoute, ReviewOut, TrendRank
from internal.session.state import MODE_AGENT, MODE_CHAT, MODE_PREVIEW
from internal.session.trace import get_node_trace, node_trace_recording
from schemas.contracts import DraftCopy, SessionBriefData
from tests.unit.session_fakes import fake_signal


@pytest.fixture
def no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: False)


@pytest.fixture
def mock_db(monkeypatch: pytest.MonkeyPatch):
    """Provide session_db context + stub repo helpers used by DB-backed nodes."""
    db = AsyncMock()

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(N, "ensure_default_personas", AsyncMock(side_effect=_noop))
    monkeypatch.setattr(N, "get_company", AsyncMock(return_value=None))
    monkeypatch.setattr(N, "list_personas", AsyncMock(return_value=[]))
    monkeypatch.setattr(N, "list_top_signals", AsyncMock(return_value=[]))
    monkeypatch.setattr(N, "get_signals_by_ids", AsyncMock(return_value=[]))
    return db


def _base_state(**extra):
    state = {
        "mode": MODE_CHAT,
        "messages": [{"role": "user", "content": "幫我做帖"}],
        "company_id": "11111111-1111-1111-1111-111111111111",
        "draft": {},
        "source_signal_ids": [],
    }
    state.update(extra)
    return state


@pytest.mark.asyncio
async def test_route_intent_heuristic_without_llm(no_llm: None) -> None:
    with node_trace_recording() as steps:
        out = await N.route_intent(_base_state())
    assert out["intent"] == "start"
    assert steps[-1].node == "route_intent"
    assert steps[-1].intent_out == "start"


@pytest.mark.asyncio
async def test_route_intent_uses_mock_llm_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)

    async def fake_complete_json(**_kwargs):
        return IntentRoute(intent="chat", rationale="general").model_dump_json()

    monkeypatch.setattr(N, "complete_json", fake_complete_json)
    out = await N.route_intent(
        _base_state(messages=[{"role": "user", "content": "天氣點"}])
    )
    assert out["intent"] == "chat"


@pytest.mark.asyncio
async def test_route_intent_blocks_confirm_outside_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)

    async def fake_complete_json(**_kwargs):
        return IntentRoute(intent="confirm_intent").model_dump_json()

    monkeypatch.setattr(N, "complete_json", fake_complete_json)
    out = await N.route_intent(_base_state(mode=MODE_CHAT))
    assert out["intent"] == "chat"


@pytest.mark.asyncio
async def test_chat_fallback_without_llm(no_llm: None) -> None:
    with node_trace_recording() as steps:
        out = await N.chat(_base_state(messages=[{"role": "user", "content": "你好"}]))
    assert out["mode"] == MODE_CHAT
    assert out["messages"][-1]["role"] == "assistant"
    assert "熱話" in out["messages"][-1]["content"] or "trends" in out["messages"][-1]["content"]
    assert steps[-1].node == "chat"


@pytest.mark.asyncio
async def test_ack_confirm_never_publishes(no_llm: None) -> None:
    out = await N.ack_confirm(
        _base_state(
            mode=MODE_PREVIEW,
            messages=[{"role": "user", "content": "可以出"}],
        )
    )
    assert out["pending_confirm"] is True
    text = out["messages"][-1]["content"]
    assert "Confirm" in text or "確認" in text or "發佈" in text


@pytest.mark.asyncio
async def test_load_context_sets_agent_mode(no_llm: None, mock_db) -> None:
    with session_db(mock_db):
        out = await N.load_context(_base_state())
    assert out["mode"] == MODE_AGENT
    assert "company_context" in out
    assert out["company_context"]["personas"] == []
    assert out["company_context"]["voice"]["roast_level"] == 1
    assert out["company_context"]["voice"]["craft"] == "hk_social_editor"


@pytest.mark.asyncio
async def test_trend_searcher_empty_signals(no_llm: None, mock_db) -> None:
    with session_db(mock_db):
        out = await N.trend_searcher(_base_state(company_context={"name": "Acme"}))
    assert out["source_signal_ids"] == []
    assert out["company_context"]["ranked_signals"] == []


@pytest.mark.asyncio
async def test_trend_searcher_ranks_with_mock_llm(
    monkeypatch: pytest.MonkeyPatch, mock_db
) -> None:
    signals = [
        fake_signal("sig_a", title="A"),
        fake_signal("sig_b", title="B"),
        fake_signal("sig_c", title="C"),
    ]
    monkeypatch.setattr(N, "list_top_signals", AsyncMock(return_value=signals))
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)

    async def fake_complete_json(**_kwargs):
        return TrendRank(ranked_signal_ids=["sig_c", "sig_a"], notes="prefer c").model_dump_json()

    monkeypatch.setattr(N, "complete_json", fake_complete_json)

    with session_db(mock_db):
        out = await N.trend_searcher(_base_state(company_context={"name": "Acme"}))

    assert out["source_signal_ids"] == ["sig_c", "sig_a"]
    assert out["company_context"]["trend_notes"] == "prefer c"
    ranked_ids = [s["signal_id"] for s in out["company_context"]["ranked_signals"]]
    assert ranked_ids == ["sig_c", "sig_a"]


@pytest.mark.asyncio
async def test_brainstormer_mock_llm_matches_brief_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    brief = BriefOut(
        can_do=["寫帖"],
        cannot_do=["未 Confirm 唔發佈"],
        angles=["熱搜連結品牌"],
        persona="hk_youth",
        summary="grounded brief",
    )

    async def fake_complete_json(**_kwargs):
        return brief.model_dump_json()

    monkeypatch.setattr(N, "complete_json", fake_complete_json)
    out = await N.brainstormer(
        _base_state(
            company_context={"ranked_signals": [{"signal_id": "sig_a", "title": "奶茶"}]},
            source_signal_ids=["sig_a"],
        )
    )
    parsed = SessionBriefData.model_validate(out["brief"])
    assert parsed.summary == "grounded brief"
    assert out["mode"] == MODE_AGENT


@pytest.mark.asyncio
async def test_executor_post_filters_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)

    async def fake_complete_json(**_kwargs):
        return DraftOut(
            caption="Hello HK",
            hashtags=["#HK"],
            cta="了解更多",
            source_signal_ids=["sig_a", "sig_evil"],
        ).model_dump_json()

    monkeypatch.setattr(N, "complete_json", fake_complete_json)
    out = await N.executor_post(
        _base_state(
            source_signal_ids=["sig_a", "sig_b"],
            company_context={"name": "Acme", "ranked_signals": []},
            brief={"summary": "x"},
        )
    )
    DraftCopy.model_validate(out["draft"])
    assert out["source_signal_ids"] == ["sig_a"]
    assert out["need_image"] is True


@pytest.mark.asyncio
async def test_grounding_check_ok(mock_db, monkeypatch: pytest.MonkeyPatch) -> None:
    sig = fake_signal("sig_a")
    monkeypatch.setattr(N, "get_signals_by_ids", AsyncMock(return_value=[sig]))
    with session_db(mock_db):
        out = await N.grounding_check(_base_state(source_signal_ids=["sig_a"]))
    assert out["grounding_ok"] is True
    assert out["source_signal_ids"] == ["sig_a"]


@pytest.mark.asyncio
async def test_grounding_check_missing_ids(mock_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(N, "get_signals_by_ids", AsyncMock(return_value=[]))
    with session_db(mock_db):
        out = await N.grounding_check(_base_state(source_signal_ids=["missing"]))
    assert out["grounding_ok"] is False
    assert out["source_signal_ids"] == []


@pytest.mark.asyncio
async def test_grounding_check_empty_ids_when_signals_exist(
    mock_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        N, "list_top_signals", AsyncMock(return_value=[fake_signal("sig_a")])
    )
    with session_db(mock_db):
        out = await N.grounding_check(_base_state(source_signal_ids=[]))
    assert out["grounding_ok"] is False


@pytest.mark.asyncio
async def test_reviewer_fails_when_grounding_bad(no_llm: None) -> None:
    out = await N.reviewer(
        _base_state(
            grounding_ok=False,
            reviewer_feedback="bad cites",
            draft={"caption": "x"},
        )
    )
    assert out["reviewer_passed"] is False
    assert "bad cites" in out["reviewer_feedback"]


@pytest.mark.asyncio
async def test_reviewer_mock_llm_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)

    async def fake_complete_json(**_kwargs):
        return ReviewOut(passed=True, feedback="", confidence=0.9).model_dump_json()

    monkeypatch.setattr(N, "complete_json", fake_complete_json)
    out = await N.reviewer(
        _base_state(
            grounding_ok=True,
            draft={"caption": "ok", "hashtags": [], "cta": ""},
        )
    )
    assert out["reviewer_passed"] is True


@pytest.mark.asyncio
async def test_edit_copy_fallback_appends_note(no_llm: None) -> None:
    out = await N.edit_copy(
        _base_state(
            mode=MODE_PREVIEW,
            draft={"caption": "原稿", "hashtags": ["#a"], "cta": "go"},
            messages=[{"role": "user", "content": "短啲"}],
            reviewer_feedback="",
            source_signal_ids=["sig_a"],
        )
    )
    assert "原稿" in out["draft"]["caption"]
    assert "短啲" in out["draft"]["caption"]
    DraftCopy.model_validate(out["draft"])


@pytest.mark.asyncio
async def test_executor_image_plan_fallback(no_llm: None) -> None:
    out = await N.executor_image_plan(
        _base_state(
            draft={"caption": "奶茶熱潮"},
            company_context={"name": "Acme"},
        )
    )
    assert "prompt" in out["image_plan"]
    assert "Acme" in out["image_plan"]["prompt"]
    assert out["image_plan"]["format"] == "single"
    assert out["image_format"] == "single"


@pytest.mark.asyncio
async def test_executor_image_plan_comic_fallback(no_llm: None) -> None:
    out = await N.executor_image_plan(
        _base_state(
            draft={"caption": "奶茶熱潮"},
            company_context={"name": "Acme"},
            image_format="comic_4panel",
        )
    )
    assert out["image_plan"]["format"] == "comic_4panel"
    assert len(out["image_plan"]["panels"]) == 4
    assert out["image_format"] == "comic_4panel"


@pytest.mark.asyncio
async def test_executor_image_gen_placeholder_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: False)
    out = await N.executor_image_gen(
        _base_state(thread_id="22222222-2222-2222-2222-222222222222", revision=2)
    )
    assert out["image_url"].startswith("placeholder://")
    assert "r3.png" in out["image_url"]


@pytest.mark.asyncio
async def test_executor_image_gen_errors_when_image_model_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from internal.llm.router import LlmProviderError

    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    monkeypatch.setattr(N, "resolve_image_model", lambda: None)
    with pytest.raises(LlmProviderError) as ei:
        await N.executor_image_gen(_base_state(revision=0, image_plan={"prompt": "x"}))
    assert ei.value.kind == "unsupported"
    assert "LLM_IMAGE_MODEL" in ei.value.message


@pytest.mark.asyncio
async def test_executor_image_gen_explicit_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    monkeypatch.setattr(N, "resolve_image_model", lambda: "placeholder")
    out = await N.executor_image_gen(
        _base_state(thread_id="22222222-2222-2222-2222-222222222222", revision=0)
    )
    assert out["image_url"].startswith("placeholder://")


@pytest.mark.asyncio
async def test_executor_image_gen_surfaces_unsupported_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from internal.llm.router import LlmProviderError

    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    monkeypatch.setattr(N, "resolve_image_model", lambda: "deepseek-v4-flash")

    async def boom(*, prompt: str, size: str = "1024x1024") -> str:
        raise LlmProviderError(
            "Model deepseek-v4-flash cannot generate images (wrong or chat-only model). "
            "Set LLM_IMAGE_MODEL to an image-capable id (e.g. dall-e-3).",
            model="deepseek-v4-flash",
            kind="unsupported",
        )

    monkeypatch.setattr(N, "generate_image", boom)
    with pytest.raises(LlmProviderError) as ei:
        await N.executor_image_gen(
            _base_state(image_plan={"prompt": "HK skyline editorial"})
        )
    assert ei.value.kind == "unsupported"
    assert "deepseek" in ei.value.message.lower()


@pytest.mark.asyncio
async def test_executor_image_gen_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    monkeypatch.setattr(N, "resolve_image_model", lambda: "dall-e-3")
    monkeypatch.setattr(
        N,
        "generate_image",
        AsyncMock(return_value="https://cdn.example/img.png"),
    )
    out = await N.executor_image_gen(
        _base_state(image_plan={"prompt": "bright HK cafe"})
    )
    assert out["image_url"] == "https://cdn.example/img.png"


@pytest.mark.asyncio
async def test_persist_preview_mints_token() -> None:
    out = await N.persist_preview(_base_state(revision=0))
    assert out["mode"] == MODE_PREVIEW
    assert out["revision"] == 1
    assert len(out["approval_token"]) >= 8


@pytest.mark.asyncio
async def test_review_exhausted_sets_error(no_llm: None) -> None:
    out = N.review_exhausted(
        _base_state(reviewer_feedback="too salesy", review_attempts=2)
    )
    assert "error" in out
    assert "too salesy" in out["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_trace_inactive_by_default(no_llm: None) -> None:
    await N.route_intent(_base_state())
    assert get_node_trace() == []


@pytest.mark.asyncio
async def test_mock_llm_payload_is_valid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: complete_json stubs must return JSON strings nodes can parse."""
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    seen: list[str] = []

    async def fake_complete_json(**_kwargs):
        raw = IntentRoute(intent="start").model_dump_json()
        seen.append(raw)
        json.loads(raw)
        return raw

    monkeypatch.setattr(N, "complete_json", fake_complete_json)
    await N.route_intent(_base_state())
    assert seen
