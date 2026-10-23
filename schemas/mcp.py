"""External MCP surface shapes (ADR 0051 §7).

Tool arguments and ``structuredContent`` results. ``status`` covers the whole
draft lifecycle; ``approval_token`` is never part of any result — Confirm
stays a UI click (ADR 0003).
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

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


class ConsentRequest(BaseModel):
    """POST /api/oauth/authorize body — the SPA consent decision (§3).

    ``company_id`` is required only when approving; a deny needs no company.
    """

    request_id: uuid.UUID
    company_id: uuid.UUID | None = None
    approve: bool


class ConsentResult(BaseModel):
    """POST /api/oauth/authorize response — where to send the user's browser."""

    redirect: str


class ConsentDetailsCompany(BaseModel):
    id: uuid.UUID
    name: str


class ConsentDetails(BaseModel):
    """GET /api/oauth/authorize/request response — the consent page's data."""

    client_id: str
    client_name: str
    client_host: str | None
    scopes: list[str]
    companies: list[ConsentDetailsCompany]


class ConnectedApp(BaseModel):
    """GET /api/auth/me/connected-apps row — one live grant."""

    id: uuid.UUID
    client_id: str
    client_name: str
    company_id: uuid.UUID
    scopes: list[str]
    created_at: str
    last_used_at: str | None


class OAuthTokenResponse(BaseModel):
    """POST /api/oauth/token success body (RFC 6749 §5.1)."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str
    scope: str


class OAuthErrorBody(BaseModel):
    """RFC 6749 §5.2 error — top-level ``error``, never nested under detail."""

    error: str
    error_description: str | None = None
