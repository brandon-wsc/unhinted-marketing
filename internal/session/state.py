from enum import StrEnum
from typing import Any, Literal, NotRequired, TypedDict


class SessionMode(StrEnum):
    CHAT = "CHAT"
    AGENT = "AGENT"
    PREVIEW = "PREVIEW"


# Prefer plain strings in graph state (avoid msgpack enum checkpoint warnings).
MODE_CHAT = SessionMode.CHAT.value
MODE_AGENT = SessionMode.AGENT.value
MODE_PREVIEW = SessionMode.PREVIEW.value


Intent = Literal["chat", "start", "revise", "confirm_intent"]


class SessionState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    mode: str
    company_id: str
    user_id: str
    thread_id: str
    intent: Intent
    # ADR 0009 research gate
    research_rule_pass: NotRequired[bool]
    research: NotRequired[dict[str, Any]]
    search_query: NotRequired[str]
    research_signals: NotRequired[list[dict[str, Any]]]
    brief: dict[str, Any]
    draft: dict[str, Any]
    image_plan: dict[str, Any]
    image_url: str | None
    revision: int
    source_signal_ids: list[str]
    reviewer_feedback: str
    review_attempts: int
    reviewer_passed: bool
    pending_confirm: bool
    approval_token: str | None
    need_image: bool
    # Set only for a turn that started while image-parked (ADR 0036).
    # Caption-only revises re-park with the locked plan; direction changes ignore it.
    hold_image_park: NotRequired[bool]
    grounding_ok: NotRequired[bool]
    # K1 knowledge packs — identity-only company_context; voice/audience compressed
    company_context: NotRequired[dict[str, Any]]
    voice_pack: NotRequired[dict[str, Any]]
    audience_catalog: NotRequired[list[dict[str, Any]]]
    active_persona: NotRequired[dict[str, Any] | None]
    # K2 — signals live outside company_context
    ranked_signals: NotRequired[list[dict[str, Any]]]
    trend_notes: NotRequired[str]
    # Product catalog match (session)
    primary_product: NotRequired[dict[str, Any] | None]
    related_products: NotRequired[list[dict[str, Any]]]
    product_clarify: NotRequired[bool]
    product_context_ids: NotRequired[list[str]]
    product_candidates: NotRequired[list[dict[str, Any]]]
    error: NotRequired[str]
    # Visual format for executor_image_plan (default single). Set via the
    # bundled angle_gate pick (ADR 0030), resume-image body, or revise.
    image_format: NotRequired[Literal["single", "comic_4panel"]]
    # Pending format submitted with choose-angle; consumed by angle_gate.
    chosen_image_format: NotRequired[str | None]
    # Landing-card handoff (ADR 0018) — warm trend_searcher with question signal refs.
    handoff_signal_ids: NotRequired[list[str]]
    # ADR 0028 / 0029 angle pick — set by choose-angle resume; consumed by executor_post.
    chosen_angle: NotRequired[str | None]
    # Non-matching pick text → brainstormer regenerates angles.
    angle_feedback: NotRequired[str | None]
    # ADR 0029 — optional persona slug submitted with the bundled card; sticky
    # across re-brief cycles. Omitted typed picks fall back to brief.persona.
    chosen_persona: NotRequired[str | None]
