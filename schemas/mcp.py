"""External MCP surface shapes (ADR 0051 §7).

Tool arguments and ``structuredContent`` results. ``status`` covers the whole
draft lifecycle; ``approval_token`` is never part of any result — Confirm
stays a UI click (ADR 0003).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.contracts import DraftAwaitingAnglePickData, DraftCopy, PreviewMediaItem

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

    @model_validator(mode="after")
    def _composed_fits_message(self) -> StartPostDraftArgs:
        """brief + context land in one user turn — PostMessageRequest's cap."""
        if len(self.brief) + len(self.context or "") > 8000:
            raise ValueError("brief + context must fit one message (8000 chars)")
        return self


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


# --- tool results — what lands in tools/call structuredContent -----------------


class VoiceDigest(BaseModel):
    """``voice_pack()`` fields an external client may see (§7)."""

    craft: str = ""
    roast_level: int = 0
    roast_level_label: str = ""
    locale: str = "zh-HK"
    forbidden_phrases: list[str] = Field(default_factory=list)
    tone_notes: str | None = None
    exemplar_captions: list[str] = Field(default_factory=list)


class BrandProductSummary(BaseModel):
    """Name + one-line summary — never a search_document dump (§7)."""

    name: str
    summary: str = ""


class BrandContextResult(BaseModel):
    company_name: str
    voice: VoiceDigest
    products: list[BrandProductSummary] = Field(default_factory=list)


class DraftToolResult(BaseModel):
    session_id: uuid.UUID


class TurnStarted(DraftToolResult):
    """Mutating tools — a background turn owns the session; poll get_post_draft."""

    status: Literal["running"] = "running"


class DraftCancelled(DraftToolResult):
    status: Literal["cancelled"] = "cancelled"


class AwaitingAnglePick(DraftToolResult, DraftAwaitingAnglePickData):
    """The angle park verbatim — same payload the SSE event carries (§9)."""

    status: Literal["awaiting_angle_pick"] = "awaiting_angle_pick"


class AwaitingImageOk(DraftToolResult):
    model_config = ConfigDict(populate_by_name=True)

    status: Literal["awaiting_image_ok"] = "awaiting_image_ok"
    # JSON key stays `copy`; Python name avoids shadowing BaseModel.copy.
    draft_copy: DraftCopy = Field(default_factory=DraftCopy, alias="copy")
    # The executor's image plan is prompt-owned, not a stable contract.
    image_plan: dict[str, Any] | None = None


class ReadyPreview(BaseModel):
    """Canonical draft + primary media — approval_token never leaves the server."""

    model_config = ConfigDict(populate_by_name=True)

    draft_copy: DraftCopy = Field(alias="copy")
    image_url: str | None = None
    media: list[PreviewMediaItem] = Field(default_factory=list)


class DraftReady(DraftToolResult):
    status: Literal["ready"] = "ready"
    confirm_url: str
    message: str | None = None
    preview: ReadyPreview


class AwaitingReply(DraftToolResult):
    """Turn ended outside a park or preview — answer via revise_post_draft."""

    status: Literal["awaiting_reply"] = "awaiting_reply"
    message: str | None = None


class DraftFailed(DraftToolResult):
    status: Literal["failed"] = "failed"
    error: str


PostDraftState = Annotated[
    TurnStarted
    | AwaitingAnglePick
    | AwaitingImageOk
    | DraftReady
    | AwaitingReply
    | DraftFailed
    | DraftCancelled,
    Field(discriminator="status"),
]
"""ADR 0051 §7 — every status get_post_draft can report."""


class ConsentRequest(BaseModel):
    """POST /api/oauth/authorize body — the SPA consent decision (§3).

    ``company_id`` is required only when approving; a deny needs no company.
    ``extra_scopes`` are step-up scopes the user opts into at consent
    (ADR 0051 §5); the server validates them against ``STEP_UP_SCOPES``.
    """

    request_id: uuid.UUID
    company_id: uuid.UUID | None = None
    approve: bool
    extra_scopes: list[str] = Field(default_factory=list)


class ConsentResult(BaseModel):
    """POST /api/oauth/authorize response — where to send the user's browser."""

    redirect: str


class ConsentDetailsCompany(BaseModel):
    id: uuid.UUID
    name: str


class ConsentDetails(BaseModel):
    """GET /api/oauth/authorize/request response — the consent page's data.

    ``scopes`` are what the client already requested. ``step_up_scopes`` are
    opt-in scopes the consent UI may offer (not already in ``scopes``).
    """

    client_id: str
    client_name: str
    client_host: str | None
    scopes: list[str]
    step_up_scopes: list[str] = Field(default_factory=list)
    companies: list[ConsentDetailsCompany]


class ConnectedApp(BaseModel):
    """GET /api/auth/me/connected-apps row — one live grant."""

    id: uuid.UUID
    client_id: str
    client_name: str
    company_id: uuid.UUID
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None


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
