"""On-prem first-run setup + instance settings shapes (ADR 0026)."""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from schemas.meta import DeploymentMode

EmailBackend = Literal["link", "smtp", "console"]


class SetupStatusResponse(BaseModel):
    deployment_mode: DeploymentMode
    setup_required: bool
    web_base_url: str
    env_llm_configured: bool
    env_smtp_configured: bool


class SetupEmailConfig(BaseModel):
    backend: EmailBackend = "link"
    email_from: str | None = Field(default=None, max_length=320)
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str | None = Field(default=None, max_length=255)
    smtp_password: str | None = Field(default=None, max_length=255)
    smtp_tls: bool = True


def _clean_url(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().rstrip("/")
    if cleaned and not cleaned.startswith(("http://", "https://")):
        raise ValueError("web_base_url must start with http:// or https://")
    return cleaned or None


class SetupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    organization_name: str = Field(min_length=1, max_length=200)
    web_base_url: str | None = Field(default=None, max_length=500)
    email_config: SetupEmailConfig | None = None

    _check_url = field_validator("web_base_url")(_clean_url)


class InstanceSettingsResponse(BaseModel):
    web_base_url: str
    email_backend: EmailBackend
    email_from: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password_last4: str | None
    smtp_tls: bool
    setup_completed: bool


class InstanceSettingsUpdate(BaseModel):
    """PUT semantics: omitted fields keep their current value; smtp_password
    only rotates when a non-empty value is sent (never returned back)."""

    web_base_url: str | None = Field(default=None, max_length=500)
    email_config: SetupEmailConfig | None = None

    _check_url = field_validator("web_base_url")(_clean_url)
