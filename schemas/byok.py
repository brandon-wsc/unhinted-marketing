"""Org BYOK API shapes (ADR 0020). Responses never include raw keys or ciphertext."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ProviderType = Literal["openai", "anthropic", "openai_compatible", "gemini", "vertex_ai"]
Capability = Literal["chat", "image"]
CapabilitySource = Literal["provider_metadata", "inferred", "manual"]
RoutingSlot = Literal["cheap", "medium", "strong", "image"]
KeySource = Literal["org", "env"]


class ByokProviderCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    provider_type: ProviderType
    api_key: str = Field(min_length=1, max_length=4096)
    api_base: str | None = Field(default=None, max_length=500)

    @field_validator("label", "api_key")
    @classmethod
    def strip_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("api_base")
    @classmethod
    def strip_base(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().rstrip("/")
        return cleaned or None

    @model_validator(mode="after")
    def require_base_for_compatible(self) -> ByokProviderCreate:
        if self.provider_type == "openai_compatible" and not self.api_base:
            raise ValueError("api_base is required for openai_compatible")
        return self


class ByokProviderPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    api_key: str | None = Field(default=None, max_length=4096)
    api_base: str | None = Field(default=None, max_length=500)

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("label must not be empty")
        return cleaned

    @field_validator("api_key")
    @classmethod
    def strip_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None  # empty keeps the stored key

    @field_validator("api_base")
    @classmethod
    def strip_base(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().rstrip("/")
        return cleaned or None


class ByokProviderItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    provider_type: ProviderType
    key_last4: str
    api_base: str | None
    last_verified_at: datetime | None
    last_error_kind: str | None
    verified: bool
    created_at: datetime
    updated_at: datetime


class ByokProviderList(BaseModel):
    items: list[ByokProviderItem]


class ByokModelCreate(BaseModel):
    provider_id: uuid.UUID
    model_id: str = Field(min_length=1, max_length=200)
    capability: Capability
    capability_source: CapabilitySource = "manual"

    @field_validator("model_id")
    @classmethod
    def strip_model_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("model_id must not be empty")
        return cleaned


class ByokModelItem(BaseModel):
    id: uuid.UUID
    provider_id: uuid.UUID
    provider_label: str
    provider_key_last4: str
    model_id: str
    capability: Capability
    capability_source: CapabilitySource
    last_verified_at: datetime | None
    last_error_kind: str | None
    verified: bool
    created_at: datetime
    updated_at: datetime


class ByokModelList(BaseModel):
    items: list[ByokModelItem]


class ByokDependentModel(BaseModel):
    id: uuid.UUID
    model_id: str
    slots: list[RoutingSlot] = Field(default_factory=list)


class ByokDeleteConflict(BaseModel):
    code: Literal["has_dependents"] = "has_dependents"
    models: list[ByokDependentModel] = Field(default_factory=list)
    slots: list[RoutingSlot] = Field(default_factory=list)


class ByokProviderDeleted(BaseModel):
    id: uuid.UUID
    removed_models: list[uuid.UUID]
    cleared_slots: list[RoutingSlot]


class ByokModelDeleted(BaseModel):
    id: uuid.UUID
    cleared_slots: list[RoutingSlot]


class ByokProbeResult(BaseModel):
    ok: bool
    error_kind: str | None = None


class ByokListedModel(BaseModel):
    id: str
    capability: Capability | None = None
    capability_source: CapabilitySource | None = None


class ByokModelListProxy(BaseModel):
    fetchable: bool
    models: list[ByokListedModel] = Field(default_factory=list)


class ByokRoutingSlot(BaseModel):
    slot: RoutingSlot
    source: KeySource
    registry_id: uuid.UUID | None = None
    model_id: str | None = None


class ByokRoutingResponse(BaseModel):
    slots: list[ByokRoutingSlot]


class ByokRoutingUpdate(BaseModel):
    cheap_model_id: uuid.UUID | None = None
    medium_model_id: uuid.UUID | None = None
    strong_model_id: uuid.UUID | None = None
    image_model_id: uuid.UUID | None = None
