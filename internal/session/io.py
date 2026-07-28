"""Structured I/O for session LLM nodes."""

from typing import Literal

from pydantic import BaseModel, Field


class IntentRoute(BaseModel):
    intent: Literal["chat", "start", "revise", "confirm_intent"]
    rationale: str = ""


class TrendRank(BaseModel):
    ranked_signal_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class BriefOut(BaseModel):
    can_do: list[str] = Field(default_factory=list)
    cannot_do: list[str] = Field(default_factory=list)
    angles: list[str] = Field(default_factory=list)
    persona: str | None = None
    summary: str = ""


class DraftOut(BaseModel):
    caption: str
    hashtags: list[str] = Field(default_factory=list)
    cta: str = ""
    source_signal_ids: list[str] = Field(default_factory=list)


class ReviewOut(BaseModel):
    passed: bool
    feedback: str = ""
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ImagePlanOut(BaseModel):
    prompt: str
    composition: str = ""
    style: str = ""
    avoid: list[str] = Field(default_factory=list)


class EditOut(BaseModel):
    caption: str
    hashtags: list[str] = Field(default_factory=list)
    cta: str = ""
    need_image: bool = False
    source_signal_ids: list[str] = Field(default_factory=list)
