"""Company media storage config + migrate API shapes (ADR 0025)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

StorageBackend = Literal["local", "s3"]
StorageMigrationState = Literal[
    "validating",
    "copying",
    "verifying",
    "ready_to_flip",
    "flipping",
    "completed",
    "cleaning",
    "done",
    "failed",
]


class StorageConfigUpdate(BaseModel):
    bucket: str = Field(min_length=1, max_length=255)
    endpoint_url: str | None = Field(default=None, max_length=500)
    region: str | None = Field(default=None, max_length=64)
    public_base_url: str | None = Field(default=None, max_length=500)
    access_key: str | None = Field(default=None, max_length=255)
    secret_key: str | None = Field(default=None, max_length=4096)

    @field_validator(
        "endpoint_url",
        "region",
        "public_base_url",
        "access_key",
        "secret_key",
    )
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("bucket")
    @classmethod
    def strip_bucket(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("bucket is required")
        return cleaned


class StorageTestRequest(StorageConfigUpdate):
    pass


class StorageTestResult(BaseModel):
    ok: bool
    error: str | None = None


class StorageMigrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    state: StorageMigrationState
    stats: dict[str, Any] = Field(default_factory=dict)
    error_keys: list[Any] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class StorageConfigOut(BaseModel):
    backend: StorageBackend
    bucket: str | None = None
    endpoint_url: str | None = None
    region: str = "us-east-1"
    public_base_url: str | None = None
    access_key: str | None = None
    secret_last4: str | None = None
    seeded_from_env: bool = False
    dual_write: bool = False
    can_migrate: bool = False
    migration: StorageMigrationOut | None = None
