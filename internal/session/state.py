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
    grounding_ok: NotRequired[bool]
    company_context: NotRequired[dict[str, Any]]
    error: NotRequired[str]
    # Visual format for executor_image_plan (default single). Set via resume-image body or revise.
    image_format: NotRequired[Literal["single", "comic_4panel"]]
