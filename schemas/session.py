import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.contracts import DraftCopy, PreviewMediaItem, SessionBriefData


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


class SessionListResponse(BaseModel):
    sessions: list[SessionListItem]


class UpdateSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    pinned: bool | None = None
    clear_title: bool = False


class PostMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class MessageResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    metadata: dict = Field(default_factory=dict)


class SessionMessagesResponse(BaseModel):
    session: SessionResponse
    messages: list[MessageResponse]
    # From sessions.state — so Stop/openSession can restore BriefCard without SSE.
    brief: SessionBriefData | None = None
    awaiting_image_ok: bool = False


class PostMessageResponse(BaseModel):
    session: SessionResponse
    messages: list[MessageResponse]
    interrupted: bool = False
    mode: str
    revision: int | None = None
    pending_confirm: bool = False
    approval_token: str | None = None
    events: list[dict] = Field(default_factory=list)


class StopSessionResponse(BaseModel):
    status: str  # cancelled | idle
    interrupted: bool = False
    awaiting_image_ok: bool = False


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


class UpdateDraftRequest(BaseModel):
    caption: str = Field(min_length=1, max_length=8000)
    hashtags: list[str] = Field(default_factory=list, max_length=40)
    cta: str = Field(default="", max_length=500)


class UpdateDraftResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

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

    model_config = ConfigDict(populate_by_name=True)

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
