"""Chat harness (ADR 0060) — scripted chat models, allowlist, cancel, SSE deltas.

The primary path is LangChain (``bind_tools`` + hand-rolled ``astream`` loop);
``anthropic`` / ``gemini`` / ``vertex_ai`` keep the Pydantic AI fallback, so
``live_harness_model`` and ``build_chat_agent`` stay pydantic-flavoured.
``_ScriptedChat`` is the ``GenericFakeChatModel`` + ``bind_tools`` shim the
LangChain tests script through ``set_chat_model_override``.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated, Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import InjectedToolArg, tool
from pydantic_ai.models.test import TestModel

from internal.session import harness as H
from internal.session import nodes as N
from internal.session.trace import node_trace_recording
from tests.unit.test_session_nodes import _base_state


class _ScriptedChat(GenericFakeChatModel):
    """GenericFakeChatModel that supports ``bind_tools`` and streams
    ``tool_calls`` / ``usage_metadata`` through ``astream`` chunks."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _stream(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> Any:
        msg = next(self.messages)
        msg = AIMessage(content=msg) if isinstance(msg, str) else msg
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content=msg.content if isinstance(msg.content, str) else "",
                tool_calls=msg.tool_calls,
                usage_metadata=msg.usage_metadata,
            )
        )


@pytest.fixture(autouse=True)
def _clear_chat_model_override() -> None:
    H.set_chat_model_override(None)
    yield
    H.set_chat_model_override(None)


def test_chat_agent_allowlist_excludes_publish() -> None:
    names = {t.name for t in H.chat_tools()}
    assert names == H.CHAT_TOOL_NAMES
    assert names.isdisjoint(H.PUBLISH_TOOL_NAMES)
    assert "publish_social_post" not in names


def test_pa_fallback_agent_keeps_same_allowlist() -> None:
    agent = H.build_chat_agent(model=TestModel(call_tools=[], custom_output_text="x"))
    names = H.registered_function_tool_names(agent)
    assert names == H.CHAT_TOOL_NAMES
    assert names.isdisjoint(H.PUBLISH_TOOL_NAMES)


def test_slow_probe_is_opt_in() -> None:
    prod = {t.name for t in H.chat_tools()}
    assert "slow_probe" not in prod
    spiked = {t.name for t in H.chat_tools(extra_tools=[H.slow_probe])}
    assert "slow_probe" in spiked


@pytest.mark.asyncio
async def test_chat_node_streams_delta_with_fake_model(monkeypatch: pytest.MonkeyPatch) -> None:
    published: list[tuple[str, dict]] = []

    async def _capture(_session_id: uuid.UUID, event_type: str, data: dict | None = None) -> None:
        published.append((event_type, data or {}))

    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)
    monkeypatch.setattr(H.session_event_bus, "publish", _capture)
    H.set_chat_model_override(
        _ScriptedChat(messages=iter([AIMessage(content="你好，我可以幫你睇熱話。")]))
    )
    thread = str(uuid.uuid4())
    with node_trace_recording() as steps:
        out = await N.chat(
            _base_state(
                thread_id=thread,
                messages=[{"role": "user", "content": "你好"}],
            )
        )
    assert out["messages"][-1]["content"].startswith("你好")
    assert any(etype == "message.delta" for etype, _ in published)
    assert all(etype != "confirm.completed" for etype, _ in published)
    assert steps[-1].node == "chat"


@pytest.mark.asyncio
async def test_query_market_trends_runs_without_db() -> None:
    H.set_chat_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {"name": "query_market_trends", "args": {"region": "HK"}, "id": "t1"}
                        ],
                    ),
                    AIMessage(content="signals noted"),
                ]
            )
        )
    )
    text = await H.stream_chat_reply(
        user_prompt="香港最近熱話",
        session_id=None,
        deps=H.ChatDeps(),
    )
    assert text
    assert "signals" in text.lower() or "noted" in text.lower()


@pytest.mark.asyncio
async def test_stream_chat_reply_tool_loop_feeds_deps() -> None:
    """The loop must inject ``ChatDeps`` into tools — read_attachment refuses
    with ``missing_scope`` when ids are absent, and its JSON lands back as a
    ToolMessage the model can see."""
    seen: dict = {}
    deps = H.ChatDeps()  # no company/user ids → missing_scope refusal

    @tool
    async def probe(deps: Annotated[H.ChatDeps, InjectedToolArg], marker: str) -> str:
        """Probe that records the injected deps."""
        seen["deps"] = deps
        seen["marker"] = marker
        return "probe-ok"

    H.set_chat_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "read_attachment",
                                "args": {"attachment_id": str(uuid.uuid4()), "query": "q"},
                                "id": "t1",
                            },
                            {"name": "probe", "args": {"marker": "m"}, "id": "t2"},
                        ],
                    ),
                    AIMessage(content="done"),
                ]
            )
        )
    )
    text = await H.stream_chat_reply(
        user_prompt="讀份嘢",
        session_id=None,
        deps=deps,
        extra_tools=[probe],
    )
    assert text == "done"
    assert seen["deps"] is deps
    assert seen["marker"] == "m"


@pytest.mark.asyncio
async def test_stream_chat_reply_unknown_tool_gets_error_result() -> None:
    """A tool_call for a name that isn't registered returns an error
    ToolMessage instead of raising — the loop then asks the model again."""
    H.set_chat_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {"name": "publish_social_post", "args": {}, "id": "t1"},
                        ],
                    ),
                    AIMessage(content="cannot do that"),
                ]
            )
        )
    )
    text = await H.stream_chat_reply(
        user_prompt="post it",
        session_id=None,
        deps=H.ChatDeps(),
    )
    assert text == "cannot do that"


@pytest.mark.asyncio
async def test_stream_chat_reply_cancels_mid_slow_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list = []
    monkeypatch.setattr("internal.llm.recorder.submit", sent.append)
    started = asyncio.Event()

    @tool
    async def slow_probe(deps: Annotated[H.ChatDeps, InjectedToolArg]) -> str:
        """Sleep so Stop/cancel can be observed mid-tool."""
        started.set()
        await asyncio.sleep(10)
        return "slept"

    H.set_chat_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[{"name": "slow_probe", "args": {}, "id": "t1"}],
                    ),
                    AIMessage(content="done"),
                ]
            )
        )
    )
    task = asyncio.create_task(
        H.stream_chat_reply(
            user_prompt="go",
            session_id=None,
            deps=H.ChatDeps(),
            extra_tools=[slow_probe],
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(sent) == 1
    assert sent[0].status == "cancelled"


@pytest.mark.asyncio
async def test_stream_chat_reply_records_call_context(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal.llm import recorder

    sent: list = []
    monkeypatch.setattr(recorder, "submit", sent.append)
    H.set_chat_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    AIMessage(
                        content="hello from test",
                        usage_metadata={"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
                    )
                ]
            )
        )
    )
    sid = uuid.uuid4()
    with recorder.call_context(caller="node:chat", node="chat", session_id=str(sid)):
        text = await H.stream_chat_reply(
            user_prompt="hi",
            session_id=None,
            deps=H.ChatDeps(),
        )
    assert text == "hello from test"
    assert len(sent) == 1
    rec = sent[0]
    assert rec.kind == "chat_text"
    assert rec.status == "ok"
    assert rec.caller == "node:chat"
    assert rec.node == "chat"
    assert rec.session_id == sid
    assert rec.response_text == "hello from test"
    assert rec.user_prompt == "hi"
    assert rec.system_prompt
    assert rec.prompt_tokens is not None
    assert rec.completion_tokens is not None
    assert rec.ttft_ms is not None


# --- live model resolution ---------------------------------------------------


def test_live_chat_model_uses_openai_compatible_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "llm_api_base", "http://127.0.0.1:4000/v1")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-test")
    model = H.live_chat_model()
    assert getattr(model, "model_name", None)


def test_live_lc_chat_model_openai_compatible(monkeypatch: pytest.MonkeyPatch) -> None:
    """openai_compatible resolves to a LangChain ChatOpenAI."""
    from langchain_openai import ChatOpenAI

    from internal import config

    monkeypatch.setattr(config.settings, "llm_api_base", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-or-test")
    monkeypatch.setattr(config.settings, "llm_cheap_model", "deepseek/deepseek-v4-flash-0731")
    lc = H._live_lc_chat_model()
    assert lc is not None
    chat, label = lc
    assert isinstance(chat, ChatOpenAI)
    assert label == "deepseek/deepseek-v4-flash-0731"


def test_live_lc_chat_model_none_for_claude_named_openai_slot() -> None:
    """A bare provider_type='openai' slot with a claude id keeps the
    ``live_harness_model`` anthropic heuristic — no LangChain model."""
    from internal.llm.resolve import CompanyLlmBundle, ResolvedModel, llm_bundle_scope

    claude = ResolvedModel(
        model_id="claude-sonnet-4-5",
        api_key="sk-ant-test",
        api_base=None,
        provider_type="openai",
        source="org",
        key_last4="test",
    )
    with llm_bundle_scope(CompanyLlmBundle(cheap=claude)):
        assert H._live_lc_chat_model() is None


def test_live_lc_chat_model_none_for_gemini() -> None:
    from internal.llm.resolve import CompanyLlmBundle, ResolvedModel, llm_bundle_scope

    gemini = ResolvedModel(
        model_id="gemini-2.5-flash",
        api_key="AIza-test",
        api_base=None,
        provider_type="gemini",
        source="org",
        key_last4="test",
    )
    with llm_bundle_scope(CompanyLlmBundle(cheap=gemini)):
        assert H._live_lc_chat_model() is None


def test_live_harness_keeps_openrouter_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config
    from internal.llm.router import ModelTier

    monkeypatch.setattr(config.settings, "llm_api_base", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-or-test")
    monkeypatch.setattr(config.settings, "llm_cheap_model", "deepseek/deepseek-v4-flash-0731")
    model = H.live_harness_model(ModelTier.CHEAP)
    assert getattr(model, "model_name", None) == "deepseek/deepseek-v4-flash-0731"


def test_live_harness_strips_openrouter_provider_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from internal import config
    from internal.llm.router import ModelTier

    monkeypatch.setattr(config.settings, "llm_api_base", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-or-test")
    monkeypatch.setattr(
        config.settings, "llm_cheap_model", "openrouter/bytedance-seed/seedream-4.5"
    )
    model = H.live_harness_model(ModelTier.CHEAP)
    assert getattr(model, "model_name", None) == "bytedance-seed/seedream-4.5"


def test_live_harness_uses_google_model_for_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic_ai.models.google import GoogleModel

    from internal.llm.resolve import CompanyLlmBundle, ResolvedModel, llm_bundle_scope
    from internal.llm.router import ModelTier

    gemini = ResolvedModel(
        model_id="gemini-2.5-flash",
        api_key="AIza-test",
        api_base=None,
        provider_type="gemini",
        source="org",
        key_last4="test",
    )
    with llm_bundle_scope(CompanyLlmBundle(cheap=gemini)):
        model = H.live_harness_model(ModelTier.CHEAP)
    assert isinstance(model, GoogleModel)
    assert getattr(model, "model_name", None) == "gemini-2.5-flash"


def test_live_harness_uses_google_cloud_provider_for_vertex_ai() -> None:
    from pydantic_ai.models.google import GoogleModel

    from internal.llm.resolve import CompanyLlmBundle, ResolvedModel, llm_bundle_scope
    from internal.llm.router import ModelTier

    vertex = ResolvedModel(
        model_id="gemini-2.5-flash",
        api_key="AQ-test",
        api_base=None,
        provider_type="vertex_ai",
        source="org",
        key_last4="test",
    )
    with llm_bundle_scope(CompanyLlmBundle(cheap=vertex)):
        model = H.live_harness_model(ModelTier.CHEAP)
    assert isinstance(model, GoogleModel)
    assert getattr(model, "model_name", None) == "gemini-2.5-flash"
    assert model.system == "google-cloud"
    assert getattr(model.client, "vertexai", None) is True
