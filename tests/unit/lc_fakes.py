"""Shared scripted LangChain chat-model fakes for session harness tests.

``GenericFakeChatModel`` covers scripted replies but not ``bind_tools``
(it raises) nor tool-calls through ``astream`` chunks (it yields nothing
for empty-content messages). ``_ScriptedChat`` is the small shim the chat /
research / execute harness tests script through the ``set_*_model_override``
hooks: ``bind_tools`` returns ``self`` so the hand-rolled loops can bind,
``_stream`` re-emits each scripted ``AIMessage`` as a chunk carrying
``tool_calls`` / ``usage_metadata``, and ``_generate`` (inherited) pops the
same queue for the non-streaming ``ainvoke`` paths.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk


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


def out_call(out_name: str, args: dict, *, usage: dict | None = None) -> AIMessage:
    """Scripted "call the output schema" reply — how typed-output loops end."""
    return AIMessage(
        content="",
        tool_calls=[{"name": out_name, "args": dict(args), "id": "out-1"}],
        usage_metadata=usage,
    )
