import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LlmCallRecordSummary(BaseModel):
    """List-row view of one LLM call (ADR 0005) — no prompt/response bodies."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    caller: str
    node: str | None
    session_id: uuid.UUID | None
    kind: str
    tier: str | None
    model: str | None
    status: str
    latency_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    parse_ok: bool | None
    fallback_used: bool


class LlmCallRecordDetail(LlmCallRecordSummary):
    """Full record incl. prompts/response — the fine-tuning debug view."""

    user_id: uuid.UUID | None
    company_id: uuid.UUID | None
    temperature: float | None
    system_prompt: str | None
    user_prompt: str | None
    response_text: str | None
    error: dict | None


class LlmCallRecordList(BaseModel):
    items: list[LlmCallRecordSummary]
    limit: int
    offset: int
