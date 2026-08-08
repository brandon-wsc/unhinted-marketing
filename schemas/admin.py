import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LlmCallRecordSummary(BaseModel):
    """List-row view of one LLM call (ADR 0005) — no prompt/response bodies."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    caller: str
    node: str | None
    session_id: uuid.UUID | None
    turn_id: uuid.UUID | None = None
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


class NodeStepSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    session_id: uuid.UUID | None
    turn_id: uuid.UUID
    seq: int
    node: str
    mode_in: str | None
    mode_out: str | None
    intent_out: str | None
    source_signal_ids_in: list[Any] = Field(default_factory=list)
    source_signal_ids_out: list[Any] = Field(default_factory=list)
    output_keys: list[Any] = Field(default_factory=list)


class NodeStepDetail(NodeStepSummary):
    user_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    llm_calls: list[LlmCallRecordSummary] = Field(default_factory=list)


class NodeStepList(BaseModel):
    items: list[NodeStepSummary]
    limit: int
    offset: int


class TraceMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    metadata: dict[str, Any] | None = None
    created_at: datetime


class TraceDraftRevision(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    revision: int
    draft_copy: dict[str, Any]
    image_url: str | None = None
    image_plan: dict[str, Any] | None = None
    source_signal_ids: list[Any] = Field(default_factory=list)
    approval_token: str | None = None
    platform: str | None = None
    created_at: datetime


class TraceSignal(BaseModel):
    signal_id: str
    source: str
    title: str
    url: str | None = None
    excerpt: str | None = None


class TraceTurn(BaseModel):
    turn_id: uuid.UUID
    steps: list[NodeStepSummary] = Field(default_factory=list)
    llm_calls: list[LlmCallRecordSummary] = Field(default_factory=list)


class ResearchSignalHit(BaseModel):
    signal_id: str
    source: str
    title: str
    url: str | None = None
    excerpt: str | None = None
    query: str | None = None  # atomic Tavily query that produced the hit


class ResearchTurn(BaseModel):
    """One graph turn's research gate + Tavily∪PG ingest (ADR 0009)."""

    turn_id: uuid.UUID
    created_at: datetime | None = None
    research_rule_pass: bool | None = None
    semantic_route: str | None = None
    need_facts: bool | None = None
    ambiguous: bool | None = None
    ask_clarify: bool | None = None
    entity_surface: str | None = None
    search_query: str | None = None
    search_queries: list[str] = Field(default_factory=list)
    signals: list[ResearchSignalHit] = Field(default_factory=list)
    source_signal_ids: list[str] = Field(default_factory=list)
    ran_research_ingest: bool = False


class SessionResearch(BaseModel):
    session_id: uuid.UUID
    turns: list[ResearchTurn] = Field(default_factory=list)


class SessionTrace(BaseModel):
    id: uuid.UUID
    mode: str
    status: str
    company_id: uuid.UUID
    user_id: uuid.UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    messages: list[TraceMessage] = Field(default_factory=list)
    draft_revisions: list[TraceDraftRevision] = Field(default_factory=list)
    signals: list[TraceSignal] = Field(default_factory=list)
    turns: list[TraceTurn] = Field(default_factory=list)
