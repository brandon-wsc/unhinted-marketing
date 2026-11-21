"""Research harness (ADR 0060) — scripted chat models, allowlist, ingest tool, recorder.

``bind_tools`` + output-as-tool loop: the model finishes by "calling"
``QueryGenOut``, so scripted replies emit a tool_call naming the schema.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from internal.perception.tavily import TavilySearchError
from internal.session import harness as H
from internal.session import ingest as ingest_mod
from internal.session import nodes as N
from internal.session import research_harness as RH
from internal.session.context import session_db
from internal.session.io import QueryGenOut
from tests.unit.lc_fakes import _ScriptedChat, out_call
from tests.unit.test_session_nodes import _base_state


@pytest.fixture(autouse=True)
def _clear_research_model_override() -> None:
    RH.set_research_model_override(None)
    yield
    RH.set_research_model_override(None)


def _tavily_items(query: str) -> list[dict]:
    return [
        {
            "signal_id": "tavily:abc",
            "source": "tavily",
            "title": "HK trend",
            "url": "https://example.com/a",
            "excerpt": "hello",
            "metrics": {"query": query},
        }
    ]


def test_research_lc_tool_allowlist_excludes_publish() -> None:
    names = {t.name for t in RH.research_tools(RH.ResearchDeps())}
    assert names == RH.RESEARCH_TOOL_NAMES
    assert names.isdisjoint(H.PUBLISH_TOOL_NAMES)
    assert "publish_social_post" not in names


@pytest.mark.asyncio
async def test_research_agent_calls_ingest_web_search(monkeypatch: pytest.MonkeyPatch) -> None:
    fetched: list[list[str]] = []

    async def fake_fetch(_db: object, queries: list[str], **_kwargs: object) -> list[dict]:
        fetched.append(list(queries))
        return _tavily_items(queries[0] if queries else "")

    monkeypatch.setattr(ingest_mod, "fetch_and_upsert_tavily", fake_fetch)
    RH.set_research_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "ingest_web_search",
                                "args": {"query": "Hong Kong overtime"},
                                "id": "t1",
                            }
                        ],
                    ),
                    out_call(
                        "QueryGenOut",
                        {
                            "search_queries": ["Hong Kong overtime"],
                            "topic": "news",
                            "time_range": "week",
                        },
                    ),
                ]
            )
        )
    )
    deps = RH.ResearchDeps()
    with session_db(AsyncMock()):
        parsed = await RH.run_query_generator_agent("Hong Kong overtime", deps)
    assert parsed is not None
    assert parsed.atomic_queries() == ["Hong Kong overtime"]
    assert fetched, "ingest helper must run when the agent calls ingest_web_search"
    assert deps.queries_run
    assert deps.ingested
    assert deps.ingested[0]["signal_id"] == "tavily:abc"


@pytest.mark.asyncio
async def test_query_generator_stashes_ingest_via_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)

    async def fake_fetch(_db: object, queries: list[str], **_kwargs: object) -> list[dict]:
        return _tavily_items(queries[0] if queries else "")

    monkeypatch.setattr(ingest_mod, "fetch_and_upsert_tavily", fake_fetch)
    RH.set_research_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "ingest_web_search",
                                "args": {"query": "usagi"},
                                "id": "t1",
                            }
                        ],
                    ),
                    out_call(
                        "QueryGenOut",
                        {
                            "search_queries": ["usagi", "Usagi favorite food"],
                            "topic": "general",
                            "time_range": "month",
                        },
                    ),
                ]
            )
        )
    )
    with session_db(AsyncMock()):
        out = await N.query_generator(
            _base_state(
                messages=[{"role": "user", "content": "usagi想食嘅兔糧"}],
                research={"entity_surface": "usagi 兔糧", "need_facts": True},
            )
        )
    assert out["research"]["query_source"] == "llm"
    assert out["research"]["ingest_via_agent"] is True
    assert out["research"]["tavily_items"][0]["signal_id"] == "tavily:abc"


@pytest.mark.asyncio
async def test_run_query_generator_records_chat_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal.llm import recorder

    sent: list = []
    monkeypatch.setattr(recorder, "submit", sent.append)
    RH.set_research_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    out_call(
                        "QueryGenOut",
                        {
                            "search_queries": ["Hong Kong overtime"],
                            "topic": "news",
                        },
                        usage={"input_tokens": 11, "output_tokens": 13, "total_tokens": 24},
                    )
                ]
            )
        )
    )
    sid = uuid.uuid4()
    with recorder.call_context(
        caller="node:query_generator",
        node="query_generator",
        session_id=str(sid),
    ):
        parsed = await RH.run_query_generator_agent("Hong Kong overtime", RH.ResearchDeps())
    assert parsed is not None
    assert len(sent) == 1
    rec = sent[0]
    assert rec.kind == "chat_json"
    assert rec.status == "ok"
    assert rec.caller == "node:query_generator"
    assert rec.node == "query_generator"
    assert rec.session_id == sid
    assert rec.user_prompt == "Hong Kong overtime"
    assert rec.system_prompt
    assert rec.response_text
    assert rec.prompt_tokens is not None
    assert rec.completion_tokens is not None


@pytest.mark.asyncio
async def test_run_query_generator_estimates_usage_when_reply_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ainvoke reply with no usage_metadata still records an estimate."""
    from internal.llm import recorder

    sent: list = []
    monkeypatch.setattr(recorder, "submit", sent.append)
    RH.set_research_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    out_call(
                        "QueryGenOut",
                        {
                            "search_queries": ["Hong Kong overtime"],
                            "topic": "news",
                        },
                    )
                ]
            ),
            token_estimates=(9, 3),
        )
    )
    parsed = await RH.run_query_generator_agent("Hong Kong overtime", RH.ResearchDeps())
    assert parsed is not None
    rec = sent[0]
    assert (rec.prompt_tokens, rec.completion_tokens, rec.total_tokens) == (9, 3, 12)


@pytest.mark.asyncio
async def test_run_query_generator_json_text_fallback() -> None:
    """A model that answers with plain JSON text (no schema call) still parses."""
    RH.set_research_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    AIMessage(
                        content=json.dumps(
                            {
                                "search_queries": ["HK labour market"],
                                "topic": "general",
                            }
                        )
                    )
                ]
            )
        )
    )
    parsed = await RH.run_query_generator_agent("prompt", RH.ResearchDeps())
    assert parsed is not None
    assert parsed.atomic_queries() == ["HK labour market"]


@pytest.mark.asyncio
async def test_run_query_generator_parse_miss_returns_none() -> None:
    RH.set_research_model_override(
        _ScriptedChat(messages=iter([AIMessage(content="sorry, cannot help")]))
    )
    parsed = await RH.run_query_generator_agent("prompt", RH.ResearchDeps())
    assert parsed is None


def _ingest_tool(deps: RH.ResearchDeps):
    """Build the deps-bound ``ingest_web_search`` tool like the loop does."""
    return next(t for t in RH.research_tools(deps) if t.name == "ingest_web_search")


@pytest.mark.asyncio
async def test_ingest_web_search_caps_at_three_queries() -> None:
    deps = RH.ResearchDeps(queries_run=["q1", "q2", "q3"])
    out = await _ingest_tool(deps).ainvoke({"query": "q4"})
    assert json.loads(out) == []
    assert deps.queries_run == ["q1", "q2", "q3"]


@pytest.mark.asyncio
async def test_ingest_web_search_reports_no_session_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``session_db`` contextvar → error payload, never a fake empty list."""
    async def fake_fetch(*_args: object, **_kwargs: object) -> list[dict]:
        raise AssertionError("fetch must not run without a session db")

    monkeypatch.setattr(ingest_mod, "fetch_and_upsert_tavily", fake_fetch)
    deps = RH.ResearchDeps()
    out = await _ingest_tool(deps).ainvoke({"query": "hk"})
    assert json.loads(out) == [{"error": "no_session_db"}]
    assert deps.queries_run == []
    assert deps.ingested == []


@pytest.mark.asyncio
async def test_ingest_web_search_reports_tavily_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tavily outage → error payload — never a fake empty result list."""
    async def boom(*_args: object, **_kwargs: object) -> list[dict]:
        raise TavilySearchError("down")

    monkeypatch.setattr(ingest_mod, "search_tavily", boom)
    deps = RH.ResearchDeps()
    with session_db(AsyncMock()):
        out = await _ingest_tool(deps).ainvoke({"query": "hk"})
    assert json.loads(out) == [{"error": "tavily_failed"}]
    assert deps.queries_run == ["hk"]
    assert deps.ingested == []


@pytest.mark.asyncio
async def test_ingest_web_search_deps_not_in_model_schema() -> None:
    """``deps`` is bound at construction — the LLM must never see it."""
    from langchain_core.utils.function_calling import convert_to_openai_tool

    schema = convert_to_openai_tool(_ingest_tool(RH.ResearchDeps()))
    params = schema["function"]["parameters"]["properties"]
    assert "deps" not in params
    assert "query" in params


def _pg_row(signal_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        signal_id=signal_id,
        source="pg",
        title="stored signal",
        excerpt="from postgres",
        metrics={},
    )


@pytest.mark.asyncio
async def test_run_research_tool_merges_agent_queries_and_pg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sub-agent didn't ingest → deterministic fetch runs the generated queries."""
    fetched: list[list[str]] = []

    async def fake_agent(_prompt: str, _deps: RH.ResearchDeps) -> QueryGenOut:
        return QueryGenOut(
            search_queries=["HK skincare trends", "sunscreen Hong Kong"],
            topic="news",
            time_range="week",
        )

    async def fake_fetch(_db: object, queries: list[str], **_kw: object) -> list[dict]:
        fetched.append(list(queries))
        return _tavily_items(queries[0])

    async def fake_pg(_db: object, *, limit: int, region: str) -> list:
        return [_pg_row("pg:1")]

    monkeypatch.setattr(RH, "run_query_generator_agent", fake_agent)
    monkeypatch.setattr(ingest_mod, "fetch_and_upsert_tavily", fake_fetch)
    monkeypatch.setattr(RH, "list_top_signals", fake_pg)
    with session_db(AsyncMock()):
        result = await RH.run_research_tool(
            {"research": {"entity_surface": "skincare"}, "focus": "護膚"}
        )
    reply = json.loads(result.reply)
    assert fetched == [["HK skincare trends", "sunscreen Hong Kong"]]
    assert {s["signal_id"] for s in reply["signals"]} == {"tavily:abc", "pg:1"}
    update = result.state_update
    assert update["search_query"] == "HK skincare trends"
    assert update["research"]["query_source"] == "llm"
    assert update["research"]["signals_trusted"] is True
    assert update["research"]["entity_surface"] == "skincare"
    assert "tavily_items" not in update["research"]
    assert update["source_signal_ids"] == ["tavily:abc", "pg:1"]


@pytest.mark.asyncio
async def test_run_research_tool_reuses_agent_ingested_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ingest_via_agent semantics — agent-searched items are the Tavily share."""
    fetch_called = False

    async def fake_agent(_prompt: str, rdeps: RH.ResearchDeps) -> QueryGenOut:
        rdeps.queries_run.append("usagi")
        rdeps.ingested.extend(_tavily_items("usagi"))
        return QueryGenOut(search_queries=["usagi", "Usagi favorite food"])

    async def fake_fetch(*_a: object, **_kw: object) -> list[dict]:
        nonlocal fetch_called
        fetch_called = True
        return []

    async def fake_pg(_db: object, **_kw: object) -> list:
        return []

    monkeypatch.setattr(RH, "run_query_generator_agent", fake_agent)
    monkeypatch.setattr(ingest_mod, "fetch_and_upsert_tavily", fake_fetch)
    monkeypatch.setattr(RH, "list_top_signals", fake_pg)
    with session_db(AsyncMock()):
        result = await RH.run_research_tool({"research": {}})
    assert fetch_called is False
    assert result.state_update["research"]["ingest_via_agent"] is True
    assert result.state_update["research"]["signals_trusted"] is True
    assert result.state_update["research_signals"][0]["signal_id"] == "tavily:abc"


@pytest.mark.asyncio
async def test_run_research_tool_parse_miss_uses_fallback_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_agent(_prompt: str, _deps: RH.ResearchDeps) -> None:
        return None

    fetched: list[list[str]] = []

    async def fake_fetch(_db: object, queries: list[str], **_kw: object) -> list[dict]:
        fetched.append(list(queries))
        return []

    async def fake_pg(_db: object, **_kw: object) -> list:
        return []

    monkeypatch.setattr(RH, "run_query_generator_agent", fake_agent)
    monkeypatch.setattr(ingest_mod, "fetch_and_upsert_tavily", fake_fetch)
    monkeypatch.setattr(RH, "list_top_signals", fake_pg)
    with session_db(AsyncMock()):
        result = await RH.run_research_tool(
            {"entity_surface": "", "fallback_hint": "Hong Kong overtime", "research": {}}
        )
    assert fetched, "fallback queries still searched deterministically"
    assert result.state_update["research"]["query_source"] == "fallback"
    assert result.state_update["research"]["signals_trusted"] is False


@pytest.mark.asyncio
async def test_run_research_tool_no_session_db() -> None:
    result = await RH.run_research_tool({"research": {}})
    assert json.loads(result.reply) == {"error": "no_session_db"}
    assert result.state_update == {}


@pytest.mark.asyncio
async def test_run_research_tool_provider_error_fails_soft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from internal.llm.router import LlmProviderError

    async def fake_agent(_prompt: str, _deps: RH.ResearchDeps) -> QueryGenOut:
        raise LlmProviderError("down")

    monkeypatch.setattr(RH, "run_query_generator_agent", fake_agent)
    with session_db(AsyncMock()):
        result = await RH.run_research_tool({"research": {}})
    assert json.loads(result.reply) == {"error": "research_unavailable"}
    assert result.state_update == {}
