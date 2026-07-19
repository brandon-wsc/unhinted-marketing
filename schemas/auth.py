import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    organization_name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class OrganizationSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    is_active: bool
    created_at: datetime
    organizations: list[OrganizationSummary]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class MessageResponse(BaseModel):
    message: str
