"""Org social-account API shapes (ADR 0022). Responses never include raw tokens."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SocialPlatform = Literal["instagram"]


class SocialAccountUpsert(BaseModel):
    ig_user_id: str = Field(min_length=1, max_length=64)
    access_token: str = Field(min_length=8, max_length=4096)
    expires_at: datetime | None = None

    @field_validator("ig_user_id", "access_token")
    @classmethod
    def strip_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned


class SocialAccountItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    platform: SocialPlatform
    ig_user_id: str
    token_last4: str
    expires_at: datetime | None = None
    last_verified_at: datetime | None = None
    last_error_kind: str | None = None
    created_at: datetime
    updated_at: datetime


class SocialAccountList(BaseModel):
    items: list[SocialAccountItem] = Field(default_factory=list)
