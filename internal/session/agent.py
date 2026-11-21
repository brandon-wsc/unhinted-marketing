"""Session main agent — ADR 0062, ``create_agent`` vertex owning cognition.

The agent answers chat directly, runs research inline via the ``research``
tool (query-gen sub-agent + deterministic PG∪Tavily ingest), and marks
handoffs for flows still owned by outer vertices. The ``handoff`` tool only
records ``deps.intent`` / ``deps.next`` — outer conditional edges do the
routing, so parks, grounding, persist, and confirm keep their current owners.
Remaining cognition tools (draft / revise / plan_image) land in later steps;
publish-class names are never registered.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool

from internal.llm.router import ModelTier
from internal.session import harness as H
from internal.session import prompts
from internal.session import research_harness as RH
from internal.session.tiers import NODE_MODEL_TIERS

# Outer vertex names the agent may hand off to — routing targets only, never
# cognition the agent performs itself.
INTENT_VERTICES = {
    "start": "load_context",
    "revise": "edit_copy",
    "confirm_intent": "ack_confirm",
}
HANDOFF_VERTICES = frozenset(INTENT_VERTICES.values())

_model_override: BaseChatModel | None = None


@dataclass
class SessionAgentDeps(H.ChatDeps):
    # Written by the handoff tool; the node maps them onto SessionState so
    # existing downstream routing (route_after_reviewer etc.) is untouched.
    intent: str = "chat"
    next: str | None = None
    # Research tool plumbing: ``research_allowed`` mirrors the fast-rule gate
    # (research_rule_pass) so the budget stays deterministic; ``research_in``
    # is the pre-built query-generator payload; ``research_out`` receives the
    # research_ingest-shaped state slice the node merges onto SessionState.
    research_allowed: bool = False
    research_in: dict[str, Any] = field(default_factory=dict)
    research_out: dict[str, Any] | None = None


def set_agent_model_override(model: BaseChatModel | None) -> None:
    """Test hook: inject a scripted chat model. Pass None to restore live."""
    global _model_override
    _model_override = model


def handoff_tool(deps: SessionAgentDeps):
    """Build the ``handoff`` marker tool bound to this call's ``deps``."""

    @tool
    async def handoff(
        intent: Literal["start", "revise", "confirm_intent"],
    ) -> str:
        """Hand control back to the session pipeline for an action the agent must not do inline.

        ``intent``: "start" = user wants a new post/draft; "revise" = change
        the existing draft; "confirm_intent" = user is trying to confirm or
        publish (never confirm yourself — Confirm is a UI button).
        """
        deps.intent = intent
        deps.next = INTENT_VERTICES[intent]
        return f"handoff:{deps.next}"

    return handoff


def research_tool(deps: SessionAgentDeps):
    """Build the ``research`` tool — sub-agent + deterministic ingest (ADR 0062)."""

    @tool
    async def research(focus: str = "") -> str:
        """Research Hong Kong market signals for this turn (web search + stored signals).

        Generates atomic queries, searches the web via Tavily, merges with
        recent stored signals, and returns signal slices (id, title, excerpt,
        query). The session keeps the merged signals for downstream grounding,
        so call this BEFORE handoff(intent="start") when fresh trends or facts
        would help the draft, or when the user asks about current market
        topics. ``focus`` optionally steers query generation. Fails closed
        when fast rules disallowed research this turn.
        """
        if not deps.research_allowed:
            return json.dumps({"error": "research_not_allowed"})
        result = await RH.run_research_tool(
            {**deps.research_in, "focus": (focus or "").strip()[:200]}
        )
        deps.research_out = result.state_update
        return result.reply

    return research


def session_agent_tools(deps: SessionAgentDeps, extra_tools: Sequence[Any] = ()) -> list[Any]:
    """LangChain tools on the main agent — publish-class names never registered."""
    return H.with_extra_tools(
        [
            H.query_market_trends,
            H.read_attachment_tool(deps),
            research_tool(deps),
            handoff_tool(deps),
        ],
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
        extra_tools=[research_tool(deps), handoff_tool(deps), *extra_tools],
        system=prompts.SESSION_AGENT,
    )
