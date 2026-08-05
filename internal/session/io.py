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


class ImagePlanPanel(BaseModel):
    """One beat in a multi-panel comic (folded into a single image prompt)."""

    index: int = Field(ge=1, le=4)
    beat: str = Field(min_length=1, max_length=400)


class ImagePlanOut(BaseModel):
    prompt: str
    format: Literal["single", "comic_4panel"] = "single"
    composition: str = ""
    style: str = ""
    avoid: list[str] = Field(default_factory=list)
    panels: list[ImagePlanPanel] = Field(default_factory=list)


class EditOut(BaseModel):
    caption: str
    hashtags: list[str] = Field(default_factory=list)
    cta: str = ""
    need_image: bool = False
    source_signal_ids: list[str] = Field(default_factory=list)
