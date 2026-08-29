"""Pydantic AI research harness (ADR 0019) — TestModel, allowlist, ingest tool, recorder."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.models.test import TestModel

from internal.session import harness as H
from internal.session import ingest as ingest_mod
from internal.session import nodes as N
from internal.session import research_harness as RH
from internal.session.context import session_db
from tests.unit.test_session_nodes import _base_state


@pytest.fixture(autouse=True)
def _clear_research_model_override() -> None:
    RH.set_research_model_override(None)
    yield
    RH.set_research_model_override(None)


def test_research_agent_allowlist_excludes_publish() -> None:
    agent = RH.build_research_agent(
        model=TestModel(
            call_tools=[],
            custom_output_args={"search_queries": ["Hong Kong overtime"]},
        )
    )
    names = H.registered_function_tool_names(agent)
    assert names == RH.RESEARCH_TOOL_NAMES
    assert names.isdisjoint(H.PUBLISH_TOOL_NAMES)
    assert "publish_social_post" not in names


@pytest.mark.asyncio
async def test_research_agent_calls_ingest_web_search(monkeypatch: pytest.MonkeyPatch) -> None:
    fetched: list[list[str]] = []

    async def fake_fetch(_db: object, queries: list[str], **_kwargs: object) -> list[dict]:
        fetched.append(list(queries))
        q = queries[0] if queries else ""
        return [
            {
                "signal_id": "tavily:abc",
                "source": "tavily",
                "title": "HK trend",
                "url": "https://example.com/a",
                "excerpt": "hello",
                "metrics": {"query": q},
            }
        ]

    monkeypatch.setattr(ingest_mod, "fetch_and_upsert_tavily", fake_fetch)
    RH.set_research_model_override(
        TestModel(
            call_tools=["ingest_web_search"],
            custom_output_args={
                "search_queries": ["Hong Kong overtime"],
                "topic": "news",
                "time_range": "week",
            },
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
        q = queries[0] if queries else ""
        return [
            {
                "signal_id": "tavily:abc",
                "source": "tavily",
                "title": "HK trend",
                "excerpt": "hello",
                "metrics": {"query": q},
            }
        ]

    monkeypatch.setattr(ingest_mod, "fetch_and_upsert_tavily", fake_fetch)
    RH.set_research_model_override(
        TestModel(
            call_tools=["ingest_web_search"],
            custom_output_args={
                "search_queries": ["usagi", "Usagi favorite food"],
                "topic": "general",
                "time_range": "month",
            },
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
        TestModel(
            call_tools=[],
            custom_output_args={
                "search_queries": ["Hong Kong overtime"],
                "topic": "news",
            },
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
async def test_ingest_web_search_caps_at_three_queries() -> None:
    deps = RH.ResearchDeps(queries_run=["q1", "q2", "q3"])

    class _Ctx:
        def __init__(self, inner: RH.ResearchDeps) -> None:
            self.deps = inner

    out = await RH.ingest_web_search(_Ctx(deps), query="q4")  # type: ignore[arg-type]
    assert out == []
    assert deps.queries_run == ["q1", "q2", "q3"]
