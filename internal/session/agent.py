"""Session main agent — ADR 0062, ``create_agent`` vertex owning cognition.

The agent answers chat directly, researches inline via the ``research`` tool,
prepares drafts via ``propose_angles``, writes them via ``draft_post``, and
edits them via ``revise_draft``, and scripts images via ``plan_image``
(DraftOut/EditOut/ImagePlanOut sub-calls). ``handoff`` only records
``deps.intent`` / ``deps.next`` — outer conditional edges do the routing, so
the angle park, image Execute park, grounding, reviewer cap, persist, and
confirm keep their current owners. Publish-class names are never registered.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool

from internal.llm.router import ModelTier, resolve_model
from internal.session import draft_harness as DH
from internal.session import harness as H
from internal.session import image_harness as IH
from internal.session import prompts
from internal.session import research_harness as RH
from internal.session.events import session_event_bus
from internal.session.io import offered_angles
from internal.session.tiers import NODE_MODEL_TIERS

logger = logging.getLogger(__name__)

# Outer vertex names the agent may hand off to — routing targets only, never
# cognition the agent performs itself. "start" lands on the angle park;
# "grounding_check" is written by draft tools, never by handoff — a draft
# cannot skip it.
INTENT_VERTICES = {
    "start": "angle_gate",
    "confirm_intent": "ack_confirm",
    "to_preview": "persist_preview",
}
HANDOFF_VERTICES = frozenset(
    {*INTENT_VERTICES.values(), "grounding_check", "executor_image_gen"}
)

_model_override: BaseChatModel | None = None


@dataclass
class SessionAgentDeps(H.ChatDeps):
    # Written by the handoff tool; the node maps them onto SessionState so
    # existing downstream routing (route_after_reviewer etc.) is untouched.
    intent: str = "chat"
    next: str | None = None
    session_id: uuid.UUID | None = None
    # Research tool plumbing: ``research_allowed`` mirrors the fast-rule gate
    # (research_rule_pass) so the budget stays deterministic; ``research_in``
    # is the pre-built query-generator payload; ``research_out`` receives the
    # research_ingest-shaped state slice the node merges onto SessionState.
    research_allowed: bool = False
    research_in: dict[str, Any] = field(default_factory=dict)
    research_out: dict[str, Any] | None = None
    # propose_angles plumbing: ``draft_in`` is the pre-built context payload;
    # ``draft_out`` receives the state slice; ``draft_ready`` gates
    # handoff("start") so a draft never proceeds without a brief.
    draft_in: dict[str, Any] = field(default_factory=dict)
    draft_out: dict[str, Any] | None = None
    draft_ready: bool = False
    # draft_post / revise_draft write here; the node merges it and routes the
    # turn into grounding_check — an outer edge, not an agent decision.
    write_out: dict[str, Any] | None = None
    # plan_image writes image_plan here → node routes to the executor_image_gen
    # park; handoff("to_preview") writes {"need_image": False} for a skip.
    image_out: dict[str, Any] | None = None


def set_agent_model_override(model: BaseChatModel | None) -> None:
    """Test hook: inject a scripted chat model. Pass None to restore live."""
    global _model_override
    _model_override = model


async def _emit_tool_progress(deps: SessionAgentDeps, name: str, tier_key: str) -> None:
    """Per-tool ``agent.progress`` — keeps the SSE beat count the outer nodes had."""
    if not deps.session_id:
        return
    tier = NODE_MODEL_TIERS.get(tier_key)
    payload = {
        "node": name,
        "model_tier": tier.value if tier else None,
        "model": resolve_model(tier) if tier else None,
    }
    session_event_bus.record_turn_progress(deps.session_id, "agent.progress", payload)
    try:
        await session_event_bus.publish(deps.session_id, "agent.progress", payload)
    except Exception:
        logger.exception("failed to publish agent.progress (%s)", name)


def handoff_tool(deps: SessionAgentDeps):
    """Build the ``handoff`` marker tool bound to this call's ``deps``."""

    @tool
    async def handoff(
        intent: Literal["start", "confirm_intent", "to_preview"],
    ) -> str:
        """Hand control back to the session pipeline for an action the agent must not do inline.

        ``intent``: "start" = angles are ready and the user must pick one at
        the angle park (requires a propose_angles call first);
        "confirm_intent" = user is trying to confirm or publish (never
        confirm yourself — Confirm is a UI button); "to_preview" = finish by
        persisting the preview, only valid when the pipeline flagged
        need_image and you decide the draft genuinely needs no image. Edits
        never hand off — call revise_draft instead.
        """
        if intent == "start":
            if not deps.draft_ready:
                return "error: call propose_angles before handoff — the pipeline needs its brief"
            if not offered_angles((deps.draft_out or {}).get("brief")):
                return "error: brief has no angles to pick — call draft_post directly"
        if intent == "to_preview":
            if deps.draft_in.get("hold_image_park"):
                return "error: image park is awaiting — call plan_image to write the new plan"
            if not deps.draft_in.get("need_image"):
                return "error: nothing awaiting a preview — reply or use a draft tool"
            deps.image_out = {"need_image": False}
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
        so call this BEFORE propose_angles when fresh trends or facts would
        help the draft, or when the user asks about current market topics.
        ``focus`` optionally steers query generation. Fails closed when fast
        rules disallowed research this turn.
        """
        if not deps.research_allowed:
            return json.dumps({"error": "research_not_allowed"})
        await _emit_tool_progress(deps, "research", "query_generator")
        result = await RH.run_research_tool(
            {**deps.research_in, "focus": (focus or "").strip()[:200]}
        )
        deps.research_out = result.state_update
        return result.reply

    return research


def propose_angles_tool(deps: SessionAgentDeps):
    """Build the ``propose_angles`` tool — draft context + BriefOut (ADR 0062)."""

    @tool
    async def propose_angles(notes: str = "") -> str:
        """Prepare post angles: assemble context, rank signals, match products, brainstorm.

        Loads the company/voice/audience context, ranks the best signals
        (from a prior research call or stored ones), matches the product
        catalog, and returns angle options plus a recommended pick. The
        session keeps the brief for the angle-pick step — call this BEFORE
        handoff(intent="start"). It may return ``{"clarify": true,
        "candidates": [...]}`` when the product is ambiguous: ask the user
        which product, then call again. ``notes`` optionally steers the
        brainstorm (e.g. feedback on prior angles).
        """
        await _emit_tool_progress(deps, "propose_angles", "brainstormer")
        result = await DH.run_propose_angles(
            {**deps.draft_in, "agent_notes": (notes or "").strip()[:400]}
        )
        deps.draft_out = result.state_update
        deps.draft_ready = result.ready
        return result.reply

    return propose_angles


def draft_post_tool(deps: SessionAgentDeps):
    """Build the ``draft_post`` tool — DraftOut sub-agent (ADR 0062)."""

    @tool
    async def draft_post() -> str:
        """Write the post draft once the angle pick is resolved.

        Runs the DraftOut sub-agent over the session's brief, signals and
        product context, then stores the draft — the outer pipeline takes it
        through grounding → review → preview automatically. The tool refuses
        while offered angles are unpicked (the angle park must run first) or
        when no brief exists (call propose_angles first). A brief with no
        angles may draft directly.
        """
        ctx = {**deps.draft_in, **(deps.draft_out or {})}
        if not ctx.get("chosen_angle"):
            if offered_angles(ctx.get("brief")):
                return "error: angles unpicked — handoff(intent=\"start\") for the angle pick"
            if not ctx.get("brief"):
                return "error: no brief — call propose_angles first"
        await _emit_tool_progress(deps, "draft_post", "executor_post")
        result = await DH.run_draft_post(ctx)
        deps.write_out = result.state_update
        return result.reply

    return draft_post


def revise_draft_tool(deps: SessionAgentDeps):
    """Build the ``revise_draft`` tool — EditOut sub-agent (ADR 0062)."""

    @tool
    async def revise_draft() -> str:
        """Revise the existing draft per the user's latest instruction.

        Runs the EditOut sub-agent; reviewer feedback rides along when the
        outer reviewer sent the turn back. The rewritten draft flows through
        grounding → review → preview automatically. Requires an existing
        draft — for a new post call propose_angles then draft_post instead.
        """
        ctx = {**deps.draft_in, **(deps.draft_out or {}), **(deps.write_out or {})}
        if not ctx.get("draft"):
            return "error: no_draft — nothing to revise; propose_angles then draft_post"
        await _emit_tool_progress(deps, "revise_draft", "edit_copy")
        result = await DH.run_revise_draft(ctx)
        deps.write_out = result.state_update
        return result.reply

    return revise_draft


def plan_image_tool(deps: SessionAgentDeps):
    """Build the ``plan_image`` tool — ImagePlanOut inner call (ADR 0062)."""

    @tool
    async def plan_image() -> str:
        """Write the image script+plan for a draft the reviewer approved.

        Callable only when the pipeline flagged need_image — the outer
        reviewer gates image work. The written plan parks at Execute (a human
        picks Discard | Execute) before any generation; you never render or
        publish. If the draft genuinely needs no image, handoff to_preview
        instead. Refuses when a draft was written this call — it must pass
        review first.
        """
        if (deps.write_out or {}).get("draft"):
            return "error: draft_changed — the new draft must pass review first"
        ctx = {**deps.draft_in, **(deps.draft_out or {})}
        if not ctx.get("need_image"):
            return "error: no_image_needed — the pipeline did not flag this draft"
        if not ctx.get("draft"):
            return "error: no_draft — nothing to plan an image for"
        await _emit_tool_progress(deps, "plan_image", "executor_image_plan")
        result = await IH.run_plan_image(ctx)
        deps.image_out = result.state_update
        return result.reply

    return plan_image


def session_agent_tools(deps: SessionAgentDeps, extra_tools: Sequence[Any] = ()) -> list[Any]:
    """LangChain tools on the main agent — publish-class names never registered."""
    return H.with_extra_tools(
        [
            H.query_market_trends,
            H.read_attachment_tool(deps),
            research_tool(deps),
            propose_angles_tool(deps),
            draft_post_tool(deps),
            revise_draft_tool(deps),
            plan_image_tool(deps),
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
        extra_tools=[
            research_tool(deps),
            propose_angles_tool(deps),
            draft_post_tool(deps),
            revise_draft_tool(deps),
            plan_image_tool(deps),
            handoff_tool(deps),
            *extra_tools,
        ],
        system=prompts.SESSION_AGENT,
    )
