"""Schema-validated external tools (ROADMAP — External Tools).

These models lock the tool boundary even when adapters are stubs or nodes
still call repos directly. Wire nodes to these shapes in a follow-up branch.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from schemas.contracts import DraftCopy


class QueryMarketTrendsRequest(BaseModel):
    """Read-only market signal lookup (background ingest + session trend_searcher)."""

    region: str = Field(default="HK", min_length=2, max_length=8)
    limit: int = Field(default=20, ge=1, le=50)
    company_id: uuid.UUID | None = None
    user_request: str | None = Field(default=None, max_length=8000)


class QueryMarketTrendsSignal(BaseModel):
    signal_id: str
    source: str
    title: str
    url: str | None = None
    excerpt: str | None = None
    region: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class QueryMarketTrendsResponse(BaseModel):
    region: str
    signals: list[QueryMarketTrendsSignal] = Field(default_factory=list)
    ranked_signal_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class PublishSocialPostRequest(BaseModel):
    """Confirm-handler adapter input only — never invoked from LangGraph (ADR 0003)."""

    model_config = ConfigDict(populate_by_name=True)

    session_id: uuid.UUID
    approval_token: str = Field(min_length=8, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=200)
    platform: str = Field(default="stub", max_length=40)
    draft_copy: DraftCopy = Field(alias="copy")
    image_url: str | None = None
    revision: int = Field(ge=0)


class PublishSocialPostResponse(BaseModel):
    receipt_id: uuid.UUID
    status: str
    tool_name: str = "publish_social_post"
    idempotency_key: str
    platform: str = "stub"
    permalink: str | None = None
    error_kind: str | None = None
