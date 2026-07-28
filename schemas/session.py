import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    company_id: uuid.UUID
    initial_message: str | None = Field(default=None, max_length=8000)


class SessionResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    user_id: uuid.UUID
    mode: str
    status: str
    created_at: datetime
    updated_at: datetime


class PostMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class MessageResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    created_at: datetime


class PostMessageResponse(BaseModel):
    session: SessionResponse
    messages: list[MessageResponse]
    interrupted: bool = False
    mode: str
    revision: int | None = None
    pending_confirm: bool = False
    approval_token: str | None = None
    events: list[dict] = Field(default_factory=list)


class ConfirmSessionRequest(BaseModel):
    approval_token: str = Field(min_length=8, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=200)
    platform: str = Field(default="stub", max_length=40)


class ConfirmSessionResponse(BaseModel):
    receipt_id: uuid.UUID
    status: str
    tool_name: str
    idempotency_key: str


class SessionEvent(BaseModel):
    type: str
    data: dict = Field(default_factory=dict)
