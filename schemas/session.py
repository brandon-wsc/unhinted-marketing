import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.contracts import AudiencePersonaOption, DraftCopy, PreviewMediaItem, SessionBriefData


class CreateSessionRequest(BaseModel):
    company_id: uuid.UUID
    initial_message: str | None = Field(default=None, max_length=8000)


class SessionResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    user_id: uuid.UUID
    mode: str
    status: str
    created_at: datetime
    updated_at: datetime


class SessionListItem(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    user_id: uuid.UUID
    mode: str
    status: str
    created_at: datetime
    updated_at: datetime
    title: str | None = None
    pinned: bool = False
    # Only set on search (?q=): context around the first matching message.
    matched_snippet: str | None = None


class SessionListResponse(BaseModel):
    sessions: list[SessionListItem]


class UpdateSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    pinned: bool | None = None
    clear_title: bool = False


class PostMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    source_question_id: str | None = Field(default=None, max_length=80)


class ForkSessionRequest(BaseModel):
    """Fork this session at a message (ADR 0017). The message must belong to the session."""

    message_id: uuid.UUID


class ForkRef(BaseModel):
    """One fork of a message — the chat it went to."""

    session_id: uuid.UUID
    title: str | None = None
    created_at: datetime


class ForkOrigin(BaseModel):
    """Where this session was forked from (None for non-forked sessions)."""

    session_id: uuid.UUID | None = None
    message_id: uuid.UUID
    title: str | None = None


class MessageResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    metadata: dict = Field(default_factory=dict)
    # Chats forked from this message (ADR 0017). Empty for most messages.
    forks: list[ForkRef] = Field(default_factory=list)


class SessionMessagesResponse(BaseModel):
    session: SessionResponse
    messages: list[MessageResponse]
    # From sessions.state — so Stop/openSession can restore BriefCard without SSE.
    brief: SessionBriefData | None = None
    awaiting_image_ok: bool = False
    # ADR 0028 / 0029 / 0030 — parked at angle_gate; brief.angles are the options.
    awaiting_angle_pick: bool = False
    personas: list[AudiencePersonaOption] = Field(default_factory=list)
    recommended_persona: str | None = None
    image_format_options: list[Literal["single", "comic_4panel"]] = Field(
        default_factory=list
    )
    # Locked format at either park (angle_gate or image) so a reload keeps the toggle.
    recommended_image_format: Literal["single", "comic_4panel"] | None = None
    # Set when this session is itself a fork (ADR 0017).
    forked_from: ForkOrigin | None = None


# Why the fork's preview may surprise the user (ADR 0017 time-aligned copy):
# carried_stale = fork kept the fork-point revision; source has newer edits.
# not_carried_later = source has a preview, but it postdates the fork point.
ForkPreviewNote = Literal["carried_stale", "not_carried_later"]


class ForkSessionResponse(SessionMessagesResponse):
    preview_note: ForkPreviewNote | None = None


class PostMessageResponse(BaseModel):
    session: SessionResponse
    messages: list[MessageResponse]
    interrupted: bool = False
    mode: str
    revision: int | None = None
    pending_confirm: bool = False
    approval_token: str | None = None
    events: list[dict] = Field(default_factory=list)


class StopSessionRequest(BaseModel):
    """ADR 0035 — interrupt keeps an in-flight turn's messages; discard wipes them."""

    mode: Literal["discard", "interrupt"] = "discard"


class StopSessionResponse(BaseModel):
    status: str  # cancelled | idle
    interrupted: bool = False
    kept: bool = False
    awaiting_image_ok: bool = False
    awaiting_angle_pick: bool = False


class ChooseAngleRequest(BaseModel):
    """ADR 0030 pick while parked at angle_gate — index or free text, optional persona + format."""

    angle_index: int | None = Field(default=None, ge=0)
    angle: str | None = Field(default=None, max_length=8000)
    persona: str | None = Field(default=None, max_length=80)
    image_format: Literal["single", "comic_4panel"] | None = None


class ChooseAngleResponse(BaseModel):
    session: SessionResponse
    messages: list[MessageResponse]
    interrupted: bool = False
    mode: str
    revision: int | None = None
    pending_confirm: bool = False
    approval_token: str | None = None
    events: list[dict] = Field(default_factory=list)


class ResumeImageRequest(BaseModel):
    """Optional visual format when continuing past the image interrupt."""

    image_format: Literal["single", "comic_4panel"] | None = None


class ResumeImageResponse(BaseModel):
    session: SessionResponse
    messages: list[MessageResponse]
    interrupted: bool = False
    mode: str
    revision: int | None = None
    pending_confirm: bool = False
    approval_token: str | None = None
    events: list[dict] = Field(default_factory=list)


class ConfirmSessionRequest(BaseModel):
    approval_token: str = Field(min_length=8, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=200)
    platform: str = Field(default="stub", max_length=40)


class ConfirmSessionResponse(BaseModel):
    receipt_id: uuid.UUID
    status: str
    tool_name: str
    idempotency_key: str
    permalink: str | None = None
    error_kind: str | None = None


class UpdateDraftRequest(BaseModel):
    caption: str = Field(min_length=1, max_length=8000)
    hashtags: list[str] = Field(default_factory=list, max_length=40)
    cta: str = Field(default="", max_length=500)


class UpdateDraftResponse(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True, json_schema_serialization_defaults_required=True
    )

    revision: int
    approval_token: str
    draft_copy: DraftCopy = Field(alias="copy")
    image_url: str | None = None
    media: list[PreviewMediaItem] = Field(default_factory=list)
    platform: str
    mode: str


class SessionMediaListResponse(BaseModel):
    media: list[PreviewMediaItem] = Field(default_factory=list)


class UpdateImagePlanRequest(BaseModel):
    plan: dict = Field(default_factory=dict)


class AddSessionImageRequest(BaseModel):
    format: Literal["single", "comic_4panel"] | str = "single"
    plan: dict | None = None


class PreviewMediaMutationResponse(BaseModel):
    """Shared shape after plan edit / regen / add (new draft revision)."""

    model_config = ConfigDict(
        populate_by_name=True, json_schema_serialization_defaults_required=True
    )

    revision: int
    approval_token: str
    draft_copy: DraftCopy = Field(alias="copy")
    image_url: str | None = None
    media: list[PreviewMediaItem] = Field(default_factory=list)
    platform: str
    mode: str


class SessionEvent(BaseModel):
    """SSE / turn event envelope. Known `type` values: schemas.contracts.SessionEventType."""

    type: str
    data: dict = Field(default_factory=dict)
