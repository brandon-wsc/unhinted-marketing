"""Chat harness (ADR 0060) — scripted chat models, allowlist, cancel, SSE deltas.

``bind_tools`` + hand-rolled ``astream`` loop; provider mapping lives in
``router._lc_harness_model`` (openai/compat → ChatOpenAI, claude-by-name →
ChatAnthropic, gemini/vertex_ai → ChatGoogleGenerativeAI). ``_ScriptedChat``
is the ``GenericFakeChatModel`` + ``bind_tools`` shim the tests script
through ``set_chat_model_override``.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import InjectedToolArg, tool

from internal.session import harness as H
from internal.session import nodes as N
from internal.session.trace import node_trace_recording
from tests.unit.lc_fakes import _ScriptedChat
from tests.unit.test_session_nodes import _base_state


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


@pytest.mark.asyncio
async def test_stream_chat_reply_estimates_usage_when_stream_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stream that never carries usage_metadata still records an estimate —
    the fallback LiteLLM used to provide (ADR 0041 accounting)."""
    from internal.llm import recorder

    sent: list = []
    monkeypatch.setattr(recorder, "submit", sent.append)
    H.set_chat_model_override(
        _ScriptedChat(
            messages=iter([AIMessage(content="hello from test")]),
            token_estimates=(20, 6),
        )
    )
    text = await H.stream_chat_reply(
        user_prompt="hi",
        session_id=None,
        deps=H.ChatDeps(),
    )
    assert text == "hello from test"
    rec = sent[0]
    assert (rec.prompt_tokens, rec.completion_tokens, rec.total_tokens) == (20, 6, 26)


@pytest.mark.asyncio
async def test_stream_chat_reply_estimates_via_text_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Message-level counting fails on custom model ids (e.g. deepseek);
    the estimate then sums per-content text counts."""
    from internal.llm import recorder

    sent: list = []
    monkeypatch.setattr(recorder, "submit", sent.append)
    H.set_chat_model_override(
        _ScriptedChat(
            messages=iter([AIMessage(content="hello from test")]),
            messages_count_fails=True,
            per_text_tokens=7,
        )
    )
    await H.stream_chat_reply(
        user_prompt="hi",
        session_id=None,
        deps=H.ChatDeps(),
    )
    rec = sent[0]
    # fallback: (System + Human) x7 prompt, reply content x7 completion
    assert (rec.prompt_tokens, rec.completion_tokens, rec.total_tokens) == (14, 7, 21)


@pytest.mark.asyncio
async def test_stream_chat_reply_null_usage_without_tokenizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No provider usage and no local tokenizer → usage stays NULL."""
    from internal.llm import recorder

    sent: list = []
    monkeypatch.setattr(recorder, "submit", sent.append)
    H.set_chat_model_override(
        _ScriptedChat(messages=iter([AIMessage(content="hello")]))
    )
    await H.stream_chat_reply(
        user_prompt="hi",
        session_id=None,
        deps=H.ChatDeps(),
    )
    rec = sent[0]
    assert rec.status == "ok"
    assert rec.prompt_tokens is None
    assert rec.total_tokens is None


# --- live model resolution ---------------------------------------------------


def test_live_lc_chat_model_openai_compatible(monkeypatch: pytest.MonkeyPatch) -> None:
    """openai_compatible resolves to a LangChain ChatOpenAI."""
    from langchain_openai import ChatOpenAI

    from internal import config

    monkeypatch.setattr(config.settings, "llm_api_base", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-or-test")
    monkeypatch.setattr(config.settings, "llm_cheap_model", "deepseek/deepseek-v4-flash-0731")
    chat, label = H._live_lc_chat_model()
    assert isinstance(chat, ChatOpenAI)
    assert label == "deepseek/deepseek-v4-flash-0731"


def test_live_lc_chat_model_anthropic_for_claude_named_openai_slot() -> None:
    """A bare provider_type='openai' slot with a claude id keeps the
    claude-by-name heuristic — routes to ChatAnthropic."""
    from langchain_anthropic import ChatAnthropic

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
        chat, label = H._live_lc_chat_model()
    assert isinstance(chat, ChatAnthropic)
    assert label == "claude-sonnet-4-5"


def test_live_lc_chat_model_google_genai_for_gemini() -> None:
    from langchain_google_genai import ChatGoogleGenerativeAI

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
        chat, label = H._live_lc_chat_model()
    assert isinstance(chat, ChatGoogleGenerativeAI)
    assert label == "gemini-2.5-flash"
    assert getattr(chat, "vertexai", None) is False


def test_live_lc_chat_model_vertexai_flag_for_vertex_slot() -> None:
    """vertex_ai rides the genai SDK's Express mode — api_key + vertexai=True."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    from internal.llm.resolve import CompanyLlmBundle, ResolvedModel, llm_bundle_scope

    vertex = ResolvedModel(
        model_id="gemini-2.5-flash",
        api_key="AQ-test",
        api_base=None,
        provider_type="vertex_ai",
        source="org",
        key_last4="test",
    )
    with llm_bundle_scope(CompanyLlmBundle(cheap=vertex)):
        chat, label = H._live_lc_chat_model()
    assert isinstance(chat, ChatGoogleGenerativeAI)
    assert label == "gemini-2.5-flash"
    assert getattr(chat, "vertexai", None) is True


def test_live_lc_chat_model_keeps_openrouter_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_openai import ChatOpenAI

    from internal import config

    monkeypatch.setattr(config.settings, "llm_api_base", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-or-test")
    monkeypatch.setattr(config.settings, "llm_cheap_model", "deepseek/deepseek-v4-flash-0731")
    chat, label = H._live_lc_chat_model()
    assert isinstance(chat, ChatOpenAI)
    assert label == "deepseek/deepseek-v4-flash-0731"
    assert getattr(chat, "model_name", None) == "deepseek/deepseek-v4-flash-0731"


def test_live_lc_chat_model_strips_openrouter_provider_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_openai import ChatOpenAI

    from internal import config

    monkeypatch.setattr(config.settings, "llm_api_base", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-or-test")
    monkeypatch.setattr(
        config.settings, "llm_cheap_model", "openrouter/bytedance-seed/seedream-4.5"
    )
    chat, label = H._live_lc_chat_model()
    assert isinstance(chat, ChatOpenAI)
    assert label == "bytedance-seed/seedream-4.5"


def test_live_lc_model_no_openai_key_is_auth_error() -> None:
    """A plain openai slot with no key fails the same way the PA path did."""
    from internal.llm.resolve import CompanyLlmBundle, ResolvedModel, llm_bundle_scope
    from internal.llm.router import LlmProviderError, ModelTier

    bare = ResolvedModel(
        model_id="gpt-4o-mini",
        api_key=None,
        api_base=None,
        provider_type="openai",
        source="org",
        key_last4=None,
    )
    with (
        llm_bundle_scope(CompanyLlmBundle(cheap=bare)),
        pytest.raises(LlmProviderError) as exc_info,
    ):
        H._live_lc_model(ModelTier.CHEAP)
    assert exc_info.value.kind == "auth"
