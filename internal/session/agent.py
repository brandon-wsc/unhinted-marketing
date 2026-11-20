"""Session main agent — ADR 0062, ``create_agent`` vertex owning cognition.

Step 1 of the incremental migration: the agent answers chat directly and
marks handoffs for flows still owned by outer vertices. The ``handoff`` tool
only records ``deps.intent`` / ``deps.next`` — outer conditional edges do the
routing, so parks, grounding, persist, and confirm keep their current owners.
Cognition tools (research / draft / revise / plan_image) land in later steps;
publish-class names are never registered.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool

from internal.llm.router import ModelTier
from internal.session import harness as H
from internal.session import prompts
from internal.session.tiers import NODE_MODEL_TIERS

# Outer vertex names the agent may hand off to — routing targets only, never
# cognition the agent performs itself.
INTENT_VERTICES = {
    "start": "load_context",
    "revise": "edit_copy",
    "confirm_intent": "ack_confirm",
}
HANDOFF_VERTICES = frozenset({"query_generator", *INTENT_VERTICES.values()})

_model_override: BaseChatModel | None = None


@dataclass
class SessionAgentDeps(H.ChatDeps):
    # Written by the handoff tool; the node maps them onto SessionState so
    # existing downstream routing (route_after_research etc.) is untouched.
    intent: str = "chat"
    next: str | None = None


def set_agent_model_override(model: BaseChatModel | None) -> None:
    """Test hook: inject a scripted chat model. Pass None to restore live."""
    global _model_override
    _model_override = model


def handoff_tool(deps: SessionAgentDeps):
    """Build the ``handoff`` marker tool bound to this call's ``deps``."""

    @tool
    async def handoff(
        intent: Literal["start", "revise", "confirm_intent", "chat"],
        research: bool = False,
    ) -> str:
        """Hand control back to the session pipeline for an action the agent must not do inline.

        ``intent``: "start" = user wants a new post/draft; "revise" = change
        the existing draft; "confirm_intent" = user is trying to confirm or
        publish (never confirm yourself — Confirm is a UI button); "chat" is
        only meaningful with research=True (ground a chat answer via web
        research first).
        ``research``: True to run market/web research before acting on the
        intent.
        """
        deps.intent = intent
        if research:
            deps.next = "query_generator"
        elif intent != "chat":
            deps.next = INTENT_VERTICES[intent]
        return f"handoff:{deps.next or 'chat'}"

    return handoff


def session_agent_tools(deps: SessionAgentDeps, extra_tools: Sequence[Any] = ()) -> list[Any]:
    """LangChain tools on the main agent — publish-class names never registered."""
    return H.with_extra_tools(
        [H.query_market_trends, H.read_attachment_tool(deps), handoff_tool(deps)],
        extra_tools,
    )


async def stream_session_agent(
    *,
    user_prompt: str,
    session_id: uuid.UUID | None,
    deps: SessionAgentDeps,
    extra_tools: Sequence[Any] = (),
) -> str | None:
    """Run the main agent, fan out message.delta, return the final text."""
    if _model_override is not None:
        chat, label = _model_override, H.model_label(_model_override)
    else:
        chat, label = H.live_lc_model(NODE_MODEL_TIERS["session_agent"] or ModelTier.CHEAP)
    return await H._stream_chat_reply_lc(
        chat=chat,
        label=label,
        user_prompt=user_prompt,
        session_id=session_id,
        deps=deps,
        extra_tools=[handoff_tool(deps), *extra_tools],
        system=prompts.SESSION_AGENT,
    )
