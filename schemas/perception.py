import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SignalMetrics(BaseModel):
    rank: int | None = None
    keyword: str | None = None
    published_at: str | None = None


class SignalResponse(BaseModel):
    signal_id: str
    source: str
    title: str
    url: str | None = None
    excerpt: str | None = None
    region: str
    metrics: dict = Field(default_factory=dict)
    ingested_at: datetime


class TopSignalsResponse(BaseModel):
    region: str
    count: int
    signals: list[SignalResponse]


class RecommendedQuestionItem(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    text: str
    rationale: str | None = None
    source_signal_ids: list[str] = Field(default_factory=list)
    persona_slug: str | None = None


class RecommendedQuestionsResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    company_id: uuid.UUID
    questions: list[RecommendedQuestionItem]
    source_signal_ids: list[str]
    generated_at: datetime
    expires_at: datetime
    is_stale: bool = False
    # Present when a run is in-flight or just failed; landing ignores this if a
    # cache row exists (scheduler / CLI refresh). SPA polls GET only on miss.
    run_status: Literal["idle", "running", "failed"] = "idle"


class RecommendedQuestionsGenerating(BaseModel):
    """202 body for the ADR 0018 fill contract — SPA polls GET with backoff."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    company_id: uuid.UUID
    run_id: uuid.UUID | None = None
    status: str = "running"  # running | failed (a fresh spawn is always running)
    retry_after_seconds: int = 3
