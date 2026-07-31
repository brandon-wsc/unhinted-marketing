import uuid
from datetime import datetime

from pydantic import BaseModel, Field


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
    id: str
    text: str
    rationale: str | None = None
    source_signal_ids: list[str] = Field(default_factory=list)
    persona_slug: str | None = None


class RecommendedQuestionsResponse(BaseModel):
    company_id: uuid.UUID
    questions: list[RecommendedQuestionItem]
    source_signal_ids: list[str]
    generated_at: datetime
    expires_at: datetime
    is_stale: bool = False
