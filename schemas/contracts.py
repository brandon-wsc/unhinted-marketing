"""Canonical draft + session SSE contracts (product SSOT for shapes).

Pydantic models here are the authority; JSON Schema mirrors live under docs/contracts/
via `python -m scripts.export_contracts`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DraftCopy(BaseModel):
    """Shared post copy across preview skins (ADR 0001)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    caption: str = ""
    hashtags: list[str] = Field(default_factory=list, max_length=40)
    cta: str = Field(default="", max_length=500)


class PreviewMediaItem(BaseModel):
    """One append-only image version referenced by a draft (ADR 0008)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    url: str | None = None
    plan: dict[str, Any] = Field(default_factory=dict)
    format: Literal["single", "comic_4panel"] | str = "single"
    role: str = "primary"
    seq: int = 0
    status: str = "ready"


class PreviewUpdatedData(BaseModel):
    """Payload for SSE / turn event `preview.updated`."""

    model_config = ConfigDict(
        populate_by_name=True, json_schema_serialization_defaults_required=True
    )

    revision: int = Field(ge=0)
    approval_token: str = Field(min_length=1)
    image_url: str | None = None  # compat: primary media url
    media: list[PreviewMediaItem] = Field(default_factory=list)
    # JSON key stays `copy` (FE / ADR); Python name avoids shadowing BaseModel.copy
    draft_copy: DraftCopy = Field(default_factory=DraftCopy, alias="copy")
    platform: str = Field(default="instagram", max_length=40)


class SessionBriefData(BaseModel):
    """Payload for `brief.updated` (matches session BriefOut / FE SessionBrief)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_do: list[str] = Field(default_factory=list)
    cannot_do: list[str] = Field(default_factory=list)
    angles: list[str] = Field(default_factory=list)
    persona: str | None = None
    summary: str = ""


class AgentProgressData(BaseModel):
    """Payload for `agent.progress`."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    node: str
    model_tier: str | None = None
    model: str | None = None


class MessageDeltaData(BaseModel):
    content: str


class MessageAssistantData(BaseModel):
    content: str = ""
    message_id: str | None = None


class DraftImageUrlData(BaseModel):
    """Payload for `draft.updated` (image URL side-effect)."""

    image_url: str | None = None


class DraftAwaitingImageOkData(BaseModel):
    """Payload for `draft.awaiting_image_ok` (interrupt before image plan)."""

    awaiting: bool = True


class LlmFailedData(BaseModel):
    error: str = "AI service unavailable"
    code: str | None = None
    kind: str | None = None
    model: str | None = None


class ReviewFailedData(BaseModel):
    error: str = ""


class TurnCancelledData(BaseModel):
    """Payload for `turn.cancelled` (ADR 0004 Stop)."""

    reason: str = "stop"
    # True when Stop cancelled in-flight resume-image and re-parked at image interrupt.
    awaiting_image_ok: bool = False


class ConfirmCompletedData(BaseModel):
    receipt_id: str
    status: str = "stubbed"
    tool_name: str = "publish_social_post"
    idempotency_key: str = ""


class SignalsUpdatedData(BaseModel):
    source_signal_ids: list[str] = Field(default_factory=list)


class SessionEventType(StrEnum):
    """Known session bus / turn event types (ADR 0002).

    Unknown string types may still appear for forward compatibility; clients
    should ignore types they do not understand.
    """

    HEARTBEAT = "heartbeat"
    SESSION_SNAPSHOT = "session.snapshot"
    MESSAGE_DELTA = "message.delta"
    MESSAGE_ASSISTANT = "message.assistant"
    AGENT_PROGRESS = "agent.progress"
    BRIEF_UPDATED = "brief.updated"
    SIGNALS_UPDATED = "signals.updated"
    DRAFT_COPY_UPDATED = "draft.copy_updated"
    DRAFT_IMAGE_PLAN_UPDATED = "draft.image_plan_updated"
    DRAFT_AWAITING_IMAGE_OK = "draft.awaiting_image_ok"
    DRAFT_UPDATED = "draft.updated"
    PREVIEW_UPDATED = "preview.updated"
    CONFIRM_PENDING = "confirm.pending"
    CONFIRM_COMPLETED = "confirm.completed"
    REVIEW_FAILED = "review.failed"
    LLM_FAILED = "llm.failed"
    TURN_CANCELLED = "turn.cancelled"


# Map event type → expected data model (documentation + export). Empty = {} only.
EVENT_PAYLOAD_MODELS: dict[SessionEventType, type[BaseModel] | None] = {
    SessionEventType.HEARTBEAT: None,
    SessionEventType.SESSION_SNAPSHOT: None,  # large hydrate blob; not a tight DTO yet
    SessionEventType.MESSAGE_DELTA: MessageDeltaData,
    SessionEventType.MESSAGE_ASSISTANT: MessageAssistantData,
    SessionEventType.AGENT_PROGRESS: AgentProgressData,
    SessionEventType.BRIEF_UPDATED: SessionBriefData,
    SessionEventType.SIGNALS_UPDATED: SignalsUpdatedData,
    SessionEventType.DRAFT_COPY_UPDATED: DraftCopy,
    SessionEventType.DRAFT_IMAGE_PLAN_UPDATED: None,  # ImagePlanOut lives in session.io
    SessionEventType.DRAFT_AWAITING_IMAGE_OK: DraftAwaitingImageOkData,
    SessionEventType.DRAFT_UPDATED: DraftImageUrlData,
    SessionEventType.PREVIEW_UPDATED: PreviewUpdatedData,
    SessionEventType.CONFIRM_PENDING: None,
    SessionEventType.CONFIRM_COMPLETED: ConfirmCompletedData,
    SessionEventType.REVIEW_FAILED: ReviewFailedData,
    SessionEventType.LLM_FAILED: LlmFailedData,
    SessionEventType.TURN_CANCELLED: TurnCancelledData,
}


class TypedSessionEvent(BaseModel):
    """Optional typed envelope when validating known events."""

    type: str
    data: dict[str, Any] = Field(default_factory=dict)

    def known_type(self) -> SessionEventType | None:
        try:
            return SessionEventType(self.type)
        except ValueError:
            return None


SessionModeLiteral = Literal["CHAT", "AGENT", "PREVIEW"]
