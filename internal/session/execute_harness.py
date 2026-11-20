"""Execute inner loop for executor_post and edit_copy — ``create_agent`` (ADR 0061).

Narrow agents: typed DraftOut / EditOut. Publish-class tools are never registered.
Graph vertices stay unchanged; Confirm remains HTTP. DraftOut/EditOut ride
the loop via ``ToolStrategy`` — the model finishes by "calling" one in the
same model call.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel

from internal.llm.router import ModelTier
from internal.session import harness as H
from internal.session import prompts
from internal.session.io import DraftOut, EditOut
from internal.session.tiers import NODE_MODEL_TIERS

EXECUTE_TOOL_NAMES = frozenset({"query_market_trends"})

_model_override: BaseChatModel | None = None
_edit_model_override: BaseChatModel | None = None


def set_execute_model_override(model: BaseChatModel | None) -> None:
    """Test hook: inject a scripted chat model. Pass None to restore live."""
    global _model_override
    _model_override = model


def set_edit_model_override(model: BaseChatModel | None) -> None:
    """Test hook for edit_copy. Pass None to restore live."""
    global _edit_model_override
    _edit_model_override = model


def execute_tools(extra_tools: Sequence[Any] = ()) -> list[Any]:
    """LangChain tools on the execute/edit loops — publish-class names never registered."""
    return H.with_extra_tools([H.query_market_trends], extra_tools)


def _caption_ok(parsed: Any) -> bool:
    return bool((parsed.caption or "").strip())


async def run_executor_post_agent(
    user_prompt: str,
) -> DraftOut | None:
    """Run the execute agent; return DraftOut or None on parse miss."""
    if _model_override is not None:
        chat, label = _model_override, H.model_label(_model_override)
    else:
        chat, label = H.live_lc_model(NODE_MODEL_TIERS["executor_post"] or ModelTier.MEDIUM)
    return await H.run_typed_lc_agent(
        chat=chat,
        label=label,
        tier=NODE_MODEL_TIERS["executor_post"],
        system=prompts.EXECUTOR_POST,
        user_prompt=user_prompt,
        tools=execute_tools(),
        out_type=DraftOut,
        is_valid=_caption_ok,
        log_tag="executor_post",
    )


async def run_edit_copy_agent(
    user_prompt: str,
) -> EditOut | None:
    """Run the edit agent; return EditOut or None on parse miss."""
    if _edit_model_override is not None:
        chat, label = _edit_model_override, H.model_label(_edit_model_override)
    else:
        chat, label = H.live_lc_model(NODE_MODEL_TIERS["edit_copy"] or ModelTier.MEDIUM)
    return await H.run_typed_lc_agent(
        chat=chat,
        label=label,
        tier=NODE_MODEL_TIERS["edit_copy"],
        system=prompts.EDIT_COPY,
        user_prompt=user_prompt,
        tools=execute_tools(),
        out_type=EditOut,
        is_valid=_caption_ok,
        log_tag="edit_copy",
    )
