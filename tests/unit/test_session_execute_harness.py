"""Execute harness (ADR 0060) — scripted chat models, allowlist, DraftOut/EditOut, recorder.

Primary path is LangChain (``bind_tools`` + output-as-tool loop); the
Pydantic AI agents stay as the anthropic/gemini/vertex fallback. The model
finishes by "calling" ``DraftOut`` / ``EditOut`` — the same mechanism
Pydantic AI used for ``output_type``.
"""

from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import AIMessage
from pydantic_ai.models.test import TestModel

from internal.session import execute_harness as EH
from internal.session import harness as H
from tests.unit.lc_fakes import _ScriptedChat, out_call


@pytest.fixture(autouse=True)
def _clear_execute_model_override() -> None:
    EH.set_execute_model_override(None)
    EH.set_edit_model_override(None)
    yield
    EH.set_execute_model_override(None)
    EH.set_edit_model_override(None)


def test_execute_lc_tool_allowlist_excludes_publish() -> None:
    names = {t.name for t in EH.execute_tools()}
    assert names == EH.EXECUTE_TOOL_NAMES
    assert names.isdisjoint(H.PUBLISH_TOOL_NAMES)
    assert "publish_social_post" not in names


def test_execute_pa_fallback_agent_keeps_same_allowlist() -> None:
    agent = EH.build_execute_agent(
        model=TestModel(
            call_tools=[],
            custom_output_args={"caption": "Hello HK"},
        )
    )
    names = H.registered_function_tool_names(agent)
    assert names == EH.EXECUTE_TOOL_NAMES
    assert names.isdisjoint(H.PUBLISH_TOOL_NAMES)
    assert "publish_social_post" not in names


@pytest.mark.asyncio
async def test_executor_post_agent_parses_draftout() -> None:
    EH.set_execute_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    out_call(
                        "DraftOut",
                        {
                            "caption": "Hello HK",
                            "hashtags": ["#HK"],
                            "cta": "了解更多",
                            "source_signal_ids": ["sig_a"],
                        },
                    )
                ]
            )
        )
    )
    parsed = await EH.run_executor_post_agent("draft me", EH.ExecuteDeps())
    assert parsed is not None
    assert parsed.caption == "Hello HK"
    assert parsed.source_signal_ids == ["sig_a"]


@pytest.mark.asyncio
async def test_execute_agent_can_call_query_market_trends() -> None:
    EH.set_execute_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "query_market_trends",
                                "args": {"region": "HK"},
                                "id": "t1",
                            }
                        ],
                    ),
                    out_call("DraftOut", {"caption": "Hello HK"}),
                ]
            )
        )
    )
    parsed = await EH.run_executor_post_agent("draft me", EH.ExecuteDeps())
    assert parsed is not None
    assert parsed.caption == "Hello HK"


@pytest.mark.asyncio
async def test_run_executor_post_records_chat_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal.llm import recorder

    sent: list = []
    monkeypatch.setattr(recorder, "submit", sent.append)
    EH.set_execute_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    out_call(
                        "DraftOut",
                        {"caption": "Hello HK", "hashtags": ["#HK"]},
                        usage={"input_tokens": 9, "output_tokens": 8, "total_tokens": 17},
                    )
                ]
            )
        )
    )
    sid = uuid.uuid4()
    with recorder.call_context(
        caller="node:executor_post",
        node="executor_post",
        session_id=str(sid),
    ):
        parsed = await EH.run_executor_post_agent("draft me", EH.ExecuteDeps())
    assert parsed is not None
    assert len(sent) == 1
    rec = sent[0]
    assert rec.kind == "chat_json"
    assert rec.status == "ok"
    assert rec.caller == "node:executor_post"
    assert rec.node == "executor_post"
    assert rec.session_id == sid
    assert rec.user_prompt == "draft me"
    assert rec.system_prompt
    assert rec.response_text
    assert rec.prompt_tokens is not None
    assert rec.completion_tokens is not None


def test_edit_pa_fallback_agent_keeps_same_allowlist() -> None:
    agent = EH.build_edit_agent(
        model=TestModel(
            call_tools=[],
            custom_output_args={"caption": "短啲 caption"},
        )
    )
    names = H.registered_function_tool_names(agent)
    assert names == EH.EXECUTE_TOOL_NAMES
    assert names.isdisjoint(H.PUBLISH_TOOL_NAMES)
    assert "publish_social_post" not in names


@pytest.mark.asyncio
async def test_edit_copy_agent_parses_editout() -> None:
    EH.set_edit_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    out_call(
                        "EditOut",
                        {
                            "caption": "短啲 caption",
                            "hashtags": ["#a"],
                            "cta": "go",
                            "need_image": True,
                            "source_signal_ids": ["sig_a"],
                        },
                    )
                ]
            )
        )
    )
    parsed = await EH.run_edit_copy_agent("shorten", EH.ExecuteDeps())
    assert parsed is not None
    assert parsed.caption == "短啲 caption"
    assert parsed.need_image is True
    assert parsed.source_signal_ids == ["sig_a"]


@pytest.mark.asyncio
async def test_edit_copy_empty_caption_is_parse_miss() -> None:
    """Empty caption trips the validity check — same contract as the PA path."""
    EH.set_edit_model_override(
        _ScriptedChat(
            messages=iter([out_call("EditOut", {"caption": "   ", "hashtags": []})])
        )
    )
    parsed = await EH.run_edit_copy_agent("shorten", EH.ExecuteDeps())
    assert parsed is None


@pytest.mark.asyncio
async def test_run_edit_copy_records_chat_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal.llm import recorder

    sent: list = []
    monkeypatch.setattr(recorder, "submit", sent.append)
    EH.set_edit_model_override(
        _ScriptedChat(
            messages=iter(
                [
                    out_call(
                        "EditOut",
                        {"caption": "短啲 caption", "need_image": False},
                        usage={"input_tokens": 7, "output_tokens": 6, "total_tokens": 13},
                    )
                ]
            )
        )
    )
    sid = uuid.uuid4()
    with recorder.call_context(
        caller="node:edit_copy",
        node="edit_copy",
        session_id=str(sid),
    ):
        parsed = await EH.run_edit_copy_agent("shorten", EH.ExecuteDeps())
    assert parsed is not None
    assert len(sent) == 1
    rec = sent[0]
    assert rec.kind == "chat_json"
    assert rec.status == "ok"
    assert rec.caller == "node:edit_copy"
    assert rec.node == "edit_copy"
    assert rec.session_id == sid
    assert rec.user_prompt == "shorten"
    assert rec.system_prompt
    assert rec.response_text
    assert rec.prompt_tokens is not None
    assert rec.completion_tokens is not None
