"""External MCP surface shapes (ADR 0051 §7).

Tool arguments and ``structuredContent`` results. ``status`` covers the whole
draft lifecycle; ``approval_token`` is never part of any result — Confirm
stays a UI click (ADR 0003).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

MCPToolStatus = Literal[
    "running",
    "awaiting_angle_pick",
    "awaiting_image_ok",
    "ready",
    "failed",
    "cancelled",
]

MCP_TOOL_NAMES = (
    "get_brand_context",
    "start_post_draft",
    "get_post_draft",
    "choose_angle",
    "approve_image",
    "revise_post_draft",
    "cancel_post_draft",
)

# §5 scope table — the only mapping between tools and scopes.
MCP_TOOL_SCOPES: dict[str, str] = {
    "get_brand_context": "knowledge:read",
    "start_post_draft": "drafts:write",
    "get_post_draft": "drafts:write",
    "choose_angle": "drafts:write",
    "approve_image": "images:generate",
    "revise_post_draft": "drafts:write",
    "cancel_post_draft": "drafts:write",
}


class StartPostDraftArgs(BaseModel):
    brief: str = Field(min_length=1, max_length=8000)
    context: str | None = Field(default=None, max_length=8000)
    auto: bool = False
    persona: str | None = None
    image_format: Literal["single", "comic_4panel"] | None = None


class SessionToolArgs(BaseModel):
    session_id: uuid.UUID


class ChooseAngleArgs(SessionToolArgs):
    angle_index: int | None = Field(default=None, ge=0)
    angle: str | None = Field(default=None, max_length=2000)
    feedback: str | None = Field(default=None, max_length=2000)
    persona: str | None = None
    image_format: Literal["single", "comic_4panel"] | None = None


class RevisePostDraftArgs(SessionToolArgs):
    instruction: str = Field(min_length=1, max_length=8000)


class ToolResult(BaseModel):
    """``structuredContent`` shared by every tool call."""

    session_id: uuid.UUID | None = None
    status: MCPToolStatus | None = None
    reason: str | None = None
    error: str | None = None
    # ready / parked payloads; angle_pick_payload keys when awaiting a pick.
    data: dict[str, Any] | None = None
