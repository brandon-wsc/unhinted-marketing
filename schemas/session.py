import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.contracts import (
    AudiencePersonaOption,
    DraftCopy,
    PreviewMediaItem,
    PreviewUpdatedData,
    SessionBriefData,
    SourceSignal,
)


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
    # ADR 0047 §8 — empty only when the message carries attachments.
    content: str = Field(max_length=8000)
    source_question_id: str | None = Field(default=None, max_length=80)
    # ADR 0047 §3 — attach this session's scratch or the member's library docs.
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _content_or_attachments(self) -> "PostMessageRequest":
        if not self.content and not self.attachment_ids:
            raise ValueError("content or attachment_ids is required")
        return self


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


AttachmentStatus = Literal["pending", "ready_lexical", "ready", "failed", "needs_ocr"]
AttachmentScope = Literal["session", "user", "org"]


class AttachmentDigest(BaseModel):
    """ADR 0047 §5 digest chip on a message that references attachments."""

    id: uuid.UUID
    filename: str
    status: AttachmentStatus
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
    # ADR 0047 — digest chips for metadata.attachment_ids refs.
    attachments: list[AttachmentDigest] = Field(default_factory=list)


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
    image_format_options: list[Literal["single", "comic_4panel"]] = Field(default_factory=list)
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
    # Latest preview after Stop. Parked discard rolls this back to the last
    # accepted revision (ADR 0036). Null when the session has no draft row.
    preview: PreviewUpdatedData | None = None


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
    """Optional format echo. Must match the locked plan; a change is a new script (ADR 0036)."""

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
    source_signals: list[SourceSignal] = Field(default_factory=list)


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
    awaiting_image_ok: bool = False
    source_signals: list[SourceSignal] = Field(default_factory=list)


class AttachmentOut(BaseModel):
    """ADR 0047 §3 attachment row — ingest flips status async via the job queue.

    ``error`` carries the readable §10 failure text; ``doc_profile`` carries
    the §5 deterministic digest (title/pages/outline/kind_guess/preview/
    partial). Both land once the ingest job has run."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID | None
    filename: str
    content_type: str
    status: AttachmentStatus
    owner_scope: AttachmentScope
    doc_profile: dict = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime


class AttachmentListResponse(BaseModel):
    """``GET /sessions/{id}/attachments`` — the session's referenced docs."""

    attachments: list[AttachmentOut]


class TranscriptPageInput(BaseModel):
    """One page of client-supplied OCR text (ADR 0048 §2)."""

    page: int = Field(ge=1)
    text: str


class AttachmentTranscriptRequest(BaseModel):
    """``POST /attachments/{id}/transcript`` — per-page OCR text produced by
    any engine (browser tesseract.js today; a worker OCR job later — same
    contract). Untrusted input: caps keep the payload bounded; ``engine`` is
    recorded as provenance, never trusted."""

    engine: str | None = Field(default=None, max_length=100)
    pages: list[TranscriptPageInput] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _cap_total_text(self) -> "AttachmentTranscriptRequest":
        total = sum(len(p.text) for p in self.pages)
        if total > 2_000_000:
            raise ValueError("Transcript exceeds the 2 MB text limit")
        return self


class SessionEvent(BaseModel):
    """SSE / turn event envelope. Known `type` values: schemas.contracts.SessionEventType."""

    type: str
    data: dict = Field(default_factory=dict)
