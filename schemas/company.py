"""Company settings API shapes (voice + products)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class CompanyVoiceSettings(BaseModel):
    company_id: uuid.UUID
    roast_level: int = Field(ge=0, le=3)
    locale: str
    forbidden_phrases: list[str] = Field(default_factory=list)
    tone_notes: str = ""
    exemplar_captions: list[str] = Field(default_factory=list)
    can_edit: bool = False


class CompanyVoiceUpdate(BaseModel):
    roast_level: int = Field(ge=0, le=3)
    locale: str = Field(min_length=2, max_length=32)
    forbidden_phrases: list[str] = Field(default_factory=list, max_length=15)
    tone_notes: str = Field(default="", max_length=2000)
    exemplar_captions: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("locale")
    @classmethod
    def strip_locale(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("locale is required")
        return cleaned

    @field_validator("forbidden_phrases")
    @classmethod
    def clean_phrases(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for raw in value:
            phrase = raw.strip()
            if phrase and phrase not in out:
                out.append(phrase)
            if len(out) >= 15:
                break
        return out

    @field_validator("tone_notes")
    @classmethod
    def strip_notes(cls, value: str) -> str:
        return value.strip()

    @field_validator("exemplar_captions")
    @classmethod
    def clean_exemplars(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in value:
            cap = raw.strip()[:150]
            if not cap or cap in seen:
                continue
            seen.add(cap)
            out.append(cap)
            if len(out) >= 3:
                break
        return out


class ExemplarPromoteRequest(BaseModel):
    """Promote a confirmed draft caption into company voice exemplars (K5)."""

    caption: str = Field(min_length=1, max_length=2000)

    @field_validator("caption")
    @classmethod
    def strip_caption(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("caption is required")
        return cleaned


class ExemplarPromoteResponse(BaseModel):
    company_id: uuid.UUID
    exemplar_captions: list[str]
    added: bool


class CompanySummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str


class CompanyUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name is required")
        return cleaned


class CompanyMember(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    display_name: str
    role: Literal["owner", "admin", "member"]
    joined_at: datetime


class CompanyMemberListResponse(BaseModel):
    company_id: uuid.UUID
    items: list[CompanyMember]


class CompanyMemberRoleUpdate(BaseModel):
    role: Literal["admin", "member"]


class ProductItem(BaseModel):
    id: uuid.UUID
    sku: str
    name: str
    status: str
    owner_scope: Literal["org", "user"]
    covered_by_company: bool = False
    profile: dict[str, str] = Field(default_factory=dict)
    updated_at: datetime


class ProductListResponse(BaseModel):
    company_id: uuid.UUID
    scope: Literal["org", "user"]
    items: list[ProductItem]
    can_edit: bool = False


class ProductImportResponse(BaseModel):
    imported: int
    updated: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class ProductCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    sku: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=4000)

    @field_validator("name", "sku")
    @classmethod
    def strip_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("required")
        return cleaned

    @field_validator("notes")
    @classmethod
    def strip_notes(cls, value: str) -> str:
        return value.strip()
