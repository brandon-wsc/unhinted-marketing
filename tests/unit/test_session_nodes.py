"""Session LangGraph nodes with mocked LLM / repos — no live API, no Postgres."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.models.test import TestModel

from internal.session import execute_harness as EH
from internal.session import nodes as N
from internal.session import research_harness as RH
from internal.session.context import session_db
from internal.session.io import (
    BriefOut,
    IntentRoute,
    QueryGenOut,
    ResearchFlags,
    ReviewOut,
    TrendRank,
)
from internal.session.state import MODE_AGENT, MODE_CHAT, MODE_PREVIEW
from internal.session.trace import get_node_trace, node_trace_recording
from schemas.contracts import DraftCopy, SessionBriefData
from tests.unit.session_fakes import fake_signal


@pytest.fixture(autouse=True)
def _clear_harness_model_overrides() -> None:
    RH.set_research_model_override(None)
    EH.set_execute_model_override(None)
    EH.set_edit_model_override(None)
    yield
    RH.set_research_model_override(None)
    EH.set_execute_model_override(None)
    EH.set_edit_model_override(None)


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
    assert out["research"]["need_facts"] is False
    assert steps[-1].node == "route_intent"
    assert steps[-1].intent_out == "start"


@pytest.mark.asyncio
async def test_fast_rule_checker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "internal.session.semantic_gate.classify_semantic_route",
        lambda _t: "chitchat",
    )
    out = await N.fast_rule_checker(
        _base_state(messages=[{"role": "user", "content": "你好"}])
    )
    assert out["research_rule_pass"] is False
    assert out["research"]["semantic_route"] == "chitchat"


@pytest.mark.asyncio
async def test_route_intent_ambiguity_blocks_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)

    async def fake_complete_json(**_kwargs):
        return IntentRoute(
            intent="start",
            research=ResearchFlags(
                need_facts=True,
                ambiguous=True,
                ask_clarify=True,
                entity_surface="usagi",
            ),
        ).model_dump_json()

    monkeypatch.setattr(N, "complete_json", fake_complete_json)
    out = await N.route_intent(
        _base_state(
            research_rule_pass=True,
            messages=[{"role": "user", "content": "usagi 熱話"}],
        )
    )
    assert out["intent"] == "chat"
    assert out["research"]["ask_clarify"] is True


@pytest.mark.asyncio
async def test_query_generator_normalize_without_llm(no_llm: None) -> None:
    out = await N.query_generator(
        _base_state(messages=[{"role": "user", "content": "香港加班"}])
    )
    assert "search_query" in out
    assert "Hong Kong" in out["search_query"] or "香港" in out["search_query"]
    assert out["research"]["query_source"] == "normalize"


@pytest.mark.asyncio
async def test_query_generator_first_turn_keyword_still_cheap_path(no_llm: None) -> None:
    out = await N.query_generator(
        _base_state(messages=[{"role": "user", "content": "Chiikawa"}])
    )
    assert "Hong Kong" in out["search_query"]
    assert out["research"]["query_source"] == "normalize"
    assert out["research"]["search_queries"] == [out["search_query"]]


@pytest.mark.asyncio
async def test_query_generator_colloquial_uses_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    RH.set_research_model_override(
        TestModel(
            call_tools=[],
            custom_output_args={
                "search_queries": ["usagi", "Usagi favorite food", "rabbit feed"],
                "topic": "general",
                "time_range": "month",
            },
        )
    )
    out = await N.query_generator(
        _base_state(
            messages=[{"role": "user", "content": "usagi想食嘅兔糧"}],
            research={"entity_surface": "usagi 兔糧", "need_facts": True},
        )
    )
    assert out["search_query"] == "usagi"
    assert out["research"]["query_source"] == "llm"
    assert out["research"]["search_queries"] == [
        "usagi",
        "Usagi favorite food",
        "rabbit feed",
    ]
    assert out["research"].get("ingest_via_agent") is not True


@pytest.mark.asyncio
async def test_query_generator_accepts_null_optional_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional fields omitted must keep LLM search_queries, not gloss fallback."""
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    RH.set_research_model_override(
        TestModel(
            call_tools=[],
            custom_output_args={
                "search_queries": ["Usagi food preferences", "Usagi rabbit diet"],
                "topic": "general",
            },
        )
    )
    out = await N.query_generator(
        _base_state(
            messages=[{"role": "user", "content": "Usagi鍾意食嘅"}],
            research={"entity_surface": "Usagi 鍾意食", "need_facts": True},
        )
    )
    assert out["search_query"] == "Usagi food preferences"
    assert out["research"]["search_queries"] == [
        "Usagi food preferences",
        "Usagi rabbit diet",
    ]
    assert out["research"]["tavily_topic"] == "general"
    assert out["research"]["query_source"] == "llm"


@pytest.mark.asyncio
async def test_query_generator_follow_up_skips_cheap_hk_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    captured: dict[str, str] = {}
    orig = RH.run_query_generator_agent

    async def wrapped(user_prompt: str, deps: RH.ResearchDeps) -> QueryGenOut | None:
        captured["user"] = user_prompt
        return await orig(user_prompt, deps)

    monkeypatch.setattr(RH, "run_query_generator_agent", wrapped)
    RH.set_research_model_override(
        TestModel(
            call_tools=[],
            custom_output_args={
                "search_queries": ["Chiikawa Usagi", "Chiikawa Usagi favorite food"],
                "topic": "general",
            },
        )
    )
    out = await N.query_generator(
        _base_state(
            messages=[
                {"role": "user", "content": "usagi想食嘅兔糧"},
                {"role": "assistant", "content": "你講邊個 Usagi？"},
                {"role": "user", "content": "Chiikawa"},
            ],
            research={"entity_surface": "Chiikawa Usagi 兔糧", "need_facts": True},
        )
    )
    payload = json.loads(captured["user"])
    assert payload["last_user_message"] == "Chiikawa"
    assert any(m.get("content") == "usagi想食嘅兔糧" for m in payload["recent_thread"])
    assert "Hong Kong" not in out["search_query"]
    assert out["research"]["query_source"] == "llm"
    assert out["research"]["search_queries"] == [
        "Chiikawa Usagi",
        "Chiikawa Usagi favorite food",
    ]


@pytest.mark.asyncio
async def test_route_intent_payload_includes_recent_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    captured: dict[str, str] = {}

    async def fake_complete_json(**kwargs):
        captured["user"] = kwargs["user"]
        return IntentRoute(intent="chat", rationale="disambiguate").model_dump_json()

    monkeypatch.setattr(N, "complete_json", fake_complete_json)
    out = await N.route_intent(
        _base_state(
            research_rule_pass=True,
            messages=[
                {"role": "user", "content": "usagi想食嘅兔糧"},
                {"role": "assistant", "content": "你講邊個 Usagi？"},
                {"role": "user", "content": "Chiikawa"},
            ],
        )
    )
    payload = json.loads(captured["user"])
    assert payload["last_user_message"] == "Chiikawa"
    assert any(m.get("content") == "usagi想食嘅兔糧" for m in payload["recent_thread"])
    assert out["intent"] == "chat"


@pytest.mark.asyncio
async def test_query_generator_fallback_glosses_entity(no_llm: None) -> None:
    out = await N.query_generator(
        _base_state(
            messages=[{"role": "user", "content": "usagi想食嘅兔糧"}],
            research={"entity_surface": "usagi 兔糧", "need_facts": True},
        )
    )
    qs = out["research"]["search_queries"]
    assert all("兔糧" not in q for q in qs)
    assert any("usagi" in q.lower() for q in qs)
    assert any("rabbit food" in q.lower() for q in qs)
    assert not any("usagi" in q.lower() and "rabbit food" in q.lower() for q in qs)
    assert out["research"]["query_source"] == "fallback"


@pytest.mark.asyncio
async def test_query_generator_follow_up_fallback_uses_prior_turn(no_llm: None) -> None:
    out = await N.query_generator(
        _base_state(
            messages=[
                {"role": "user", "content": "usagi想食嘅兔糧"},
                {"role": "assistant", "content": "你講邊個 Usagi？"},
                {"role": "user", "content": "Chiikawa"},
            ],
            research={"entity_surface": "Chiikawa", "need_facts": True},
        )
    )
    qs = out["research"]["search_queries"]
    blob = " ".join(qs).lower()
    assert "rabbit food" in blob
    assert any("chiikawa" in q.lower() or "usagi" in q.lower() for q in qs)
    assert not (len(qs) == 1 and "hong kong" in qs[0].lower() and "rabbit" not in qs[0].lower())


@pytest.mark.asyncio
async def test_research_ingest_pg_and_tavily(
    monkeypatch: pytest.MonkeyPatch, mock_db
) -> None:
    monkeypatch.setattr(
        N,
        "search_tavily",
        AsyncMock(
            return_value=[
                {
                    "signal_id": "tavily:abc",
                    "source": "tavily",
                    "title": "HK trend",
                    "url": "https://example.com/a",
                    "excerpt": "hello",
                    "metrics": {"rank": 1},
                }
            ]
        ),
    )
    monkeypatch.setattr(N, "upsert_signal", AsyncMock())
    monkeypatch.setattr(
        N,
        "list_top_signals",
        AsyncMock(return_value=[fake_signal(signal_id="google_trends_hk:1", title="PG")]),
    )
    with session_db(mock_db):
        out = await N.research_ingest(
            _base_state(
                search_query="Hong Kong overtime",
                research={"search_queries": ["Hong Kong overtime", "HK work culture"]},
            )
        )
    assert out["research_signals"][0]["signal_id"] == "tavily:abc"
    assert out["research"]["signals_trusted"] is True
    assert any(s["signal_id"] == "google_trends_hk:1" for s in out["research_signals"])
    assert N.search_tavily.await_count == 2
    N.upsert_signal.assert_awaited()
    mock_db.flush.assert_awaited()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_research_ingest_untrusted_when_no_tavily(
    monkeypatch: pytest.MonkeyPatch, mock_db
) -> None:
    monkeypatch.setattr(N, "search_tavily", AsyncMock(return_value=[]))
    monkeypatch.setattr(N, "upsert_signal", AsyncMock())
    monkeypatch.setattr(
        N,
        "list_top_signals",
        AsyncMock(return_value=[fake_signal(signal_id="google_trends_hk:1", title="PG")]),
    )
    with session_db(mock_db):
        out = await N.research_ingest(
            _base_state(
                search_query="Hong Kong overtime",
                research={
                    "search_queries": ["Hong Kong overtime"],
                    "query_source": "llm",
                },
            )
        )
    assert out["research"]["signals_trusted"] is False
    assert any(s["signal_id"] == "google_trends_hk:1" for s in out["research_signals"])


@pytest.mark.asyncio
async def test_research_ingest_untrusted_when_query_fallback(
    monkeypatch: pytest.MonkeyPatch, mock_db
) -> None:
    monkeypatch.setattr(
        N,
        "search_tavily",
        AsyncMock(
            return_value=[
                {
                    "signal_id": "tavily:abc",
                    "source": "tavily",
                    "title": "HK trend",
                    "url": "https://example.com/a",
                    "excerpt": "hello",
                    "metrics": {"rank": 1},
                }
            ]
        ),
    )
    monkeypatch.setattr(N, "upsert_signal", AsyncMock())
    monkeypatch.setattr(N, "list_top_signals", AsyncMock(return_value=[]))
    with session_db(mock_db):
        out = await N.research_ingest(
            _base_state(
                search_query="Usagi Hong Kong",
                research={
                    "search_queries": ["Usagi Hong Kong"],
                    "query_source": "fallback",
                },
            )
        )
    assert out["research"]["signals_trusted"] is False
    assert out["research_signals"][0]["signal_id"] == "tavily:abc"


@pytest.mark.asyncio
async def test_research_ingest_skips_tavily_when_agent_ingested(
    monkeypatch: pytest.MonkeyPatch, mock_db
) -> None:
    tavily = AsyncMock()
    monkeypatch.setattr(N, "search_tavily", tavily)
    monkeypatch.setattr(N, "upsert_signal", AsyncMock())
    monkeypatch.setattr(
        N,
        "list_top_signals",
        AsyncMock(return_value=[fake_signal(signal_id="google_trends_hk:1", title="PG")]),
    )
    with session_db(mock_db):
        out = await N.research_ingest(
            _base_state(
                search_query="Hong Kong overtime",
                research={
                    "search_queries": ["Hong Kong overtime"],
                    "query_source": "llm",
                    "ingest_via_agent": True,
                    "tavily_items": [
                        {
                            "signal_id": "tavily:abc",
                            "source": "tavily",
                            "title": "HK trend",
                            "excerpt": "hello",
                            "metrics": {"query": "Hong Kong overtime"},
                        }
                    ],
                },
            )
        )
    tavily.assert_not_awaited()
    N.upsert_signal.assert_not_awaited()
    assert out["research_signals"][0]["signal_id"] == "tavily:abc"
    assert out["research"]["signals_trusted"] is True
    assert "tavily_items" not in out["research"]
    assert any(s["signal_id"] == "google_trends_hk:1" for s in out["research_signals"])


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
    assert "profile" not in out["company_context"]
    assert "personas" not in out["company_context"]
    assert "voice" not in out["company_context"]
    assert out["voice_pack"]["roast_level"] == 1
    assert out["voice_pack"]["craft"] == "hk_social_editor"
    assert out["voice_pack"]["locale"] == "zh-HK"
    assert out["audience_catalog"] == []


@pytest.mark.asyncio
async def test_trend_searcher_empty_signals(no_llm: None, mock_db) -> None:
    with session_db(mock_db):
        out = await N.trend_searcher(_base_state(company_context={"name": "Acme"}))
    assert out["source_signal_ids"] == []
    assert out["ranked_signals"] == []
    assert "company_context" not in out or "ranked_signals" not in (
        out.get("company_context") or {}
    )


@pytest.mark.asyncio
async def test_trend_searcher_prefers_handoff_signals(
    no_llm: None, mock_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = fake_signal("sig_q", title="咖啡節")
    monkeypatch.setattr(N, "get_signals_by_ids", AsyncMock(return_value=[handoff]))
    monkeypatch.setattr(N, "list_top_signals", AsyncMock(return_value=[]))
    with session_db(mock_db):
        out = await N.trend_searcher(
            _base_state(handoff_signal_ids=["sig_q"], company_context={"name": "Acme"})
        )
    assert out["source_signal_ids"] == ["sig_q"]
    assert out["ranked_signals"][0]["signal_id"] == "sig_q"


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
    assert out["trend_notes"] == "prefer c"
    ranked_ids = [s["signal_id"] for s in out["ranked_signals"]]
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
            company_context={"name": "Acme"},
            ranked_signals=[{"signal_id": "sig_a", "title": "奶茶"}],
            audience_catalog=[
                {"slug": "hk_youth", "label": "Youth", "hook": "short"},
            ],
            source_signal_ids=["sig_a"],
        )
    )
    parsed = SessionBriefData.model_validate(out["brief"])
    assert parsed.summary == "grounded brief"
    assert out["mode"] == MODE_AGENT
    assert out["active_persona"]["slug"] == "hk_youth"


@pytest.mark.asyncio
async def test_executor_post_filters_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    EH.set_execute_model_override(
        TestModel(
            call_tools=[],
            custom_output_args={
                "caption": "Hello HK",
                "hashtags": ["#HK"],
                "cta": "了解更多",
                "source_signal_ids": ["sig_a", "sig_evil"],
            },
        )
    )
    out = await N.executor_post(
        _base_state(
            source_signal_ids=["sig_a", "sig_b"],
            company_context={"name": "Acme"},
            ranked_signals=[],
            brief={"summary": "x"},
        )
    )
    DraftCopy.model_validate(out["draft"])
    assert out["source_signal_ids"] == ["sig_a"]
    assert out["need_image"] is True


@pytest.mark.asyncio
async def test_executor_post_fallback_without_llm(no_llm: None) -> None:
    out = await N.executor_post(
        _base_state(
            source_signal_ids=["sig_a"],
            company_context={"name": "Acme"},
            ranked_signals=[{"title": "奶茶"}],
            brief={"summary": "x"},
        )
    )
    assert "奶茶" in out["draft"]["caption"]
    assert "Acme" in out["draft"]["caption"]
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
async def test_reviewer_parse_miss_fails_closed(no_llm: None) -> None:
    out = await N.reviewer(
        _base_state(
            grounding_ok=True,
            draft={"caption": "ok", "hashtags": [], "cta": ""},
        )
    )
    assert out["reviewer_passed"] is False
    assert "JSON" not in out["reviewer_feedback"]
    assert "parse" not in out["reviewer_feedback"].lower()
    assert out["reviewer_feedback"] == N.REVIEWER_PARSE_MISS_FEEDBACK


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
async def test_edit_copy_filters_citations_and_need_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    EH.set_edit_model_override(
        TestModel(
            call_tools=[],
            custom_output_args={
                "caption": "短啲 caption",
                "hashtags": ["#a"],
                "cta": "go",
                "need_image": True,
                "source_signal_ids": ["sig_a", "sig_evil"],
            },
        )
    )
    out = await N.edit_copy(
        _base_state(
            mode=MODE_PREVIEW,
            draft={"caption": "原稿", "hashtags": ["#a"], "cta": "go"},
            messages=[{"role": "user", "content": "短啲"}],
            reviewer_feedback="",
            source_signal_ids=["sig_a", "sig_b"],
        )
    )
    DraftCopy.model_validate(out["draft"])
    assert out["draft"]["caption"] == "短啲 caption"
    assert out["source_signal_ids"] == ["sig_a"]
    assert out["need_image"] is True


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


@pytest.mark.asyncio
async def test_product_matcher_skips_when_not_needed(no_llm: None, mock_db) -> None:
    with session_db(mock_db):
        out = await N.product_matcher(
            _base_state(
                intent="start",
                user_id="22222222-2222-2222-2222-222222222222",
                research={"need_product": False, "sell_intent": "none"},
            )
        )
    assert out["primary_product"] is None
    assert out["product_clarify"] is False


@pytest.mark.asyncio
async def test_product_matcher_sets_primary(
    monkeypatch: pytest.MonkeyPatch, mock_db
) -> None:
    from types import SimpleNamespace
    from uuid import UUID

    from internal.memory.product_retrieve import ProductHit

    row = SimpleNamespace(
        id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        sku="DRK-OL-12",
        name="燕麥拿鐵",
        search_document="燕麥拿鐵 | DRK-OL-12 | 48",
        owner_scope="org",
        profile={},
    )
    hit = ProductHit(product=row, score=1.0, match_kind="exact_sku")
    monkeypatch.setattr(N, "search_products_for_member", AsyncMock(return_value=[hit]))
    with session_db(mock_db):
        out = await N.product_matcher(
            _base_state(
                intent="start",
                user_id="22222222-2222-2222-2222-222222222222",
                research={
                    "need_product": True,
                    "sell_intent": "explicit",
                    "product_surface": "DRK-OL-12",
                },
            )
        )
    assert out["product_clarify"] is False
    assert out["primary_product"]["sku"] == "DRK-OL-12"
    assert out["product_context_ids"] == ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]


@pytest.mark.asyncio
async def test_grounding_rejects_invented_product_price(
    monkeypatch: pytest.MonkeyPatch, mock_db
) -> None:
    monkeypatch.setattr(
        N,
        "get_signals_by_ids",
        AsyncMock(return_value=[fake_signal("sig_a")]),
    )
    with session_db(mock_db):
        out = await N.grounding_check(
            _base_state(
                source_signal_ids=["sig_a"],
                draft={"caption": "只需 $999 入手燕麥拿鐵"},
                primary_product={
                    "product_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "search_document": "燕麥拿鐵 | DRK-OL-12 | 48",
                },
            )
        )
    assert out["grounding_ok"] is False
    assert "999" in out["reviewer_feedback"]
