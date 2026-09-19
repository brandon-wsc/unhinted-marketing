"""On-prem first-run setup + instance settings shapes (ADR 0026)."""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from schemas.meta import DeploymentMode

EmailBackend = Literal["link", "smtp", "console"]
MetaOAuthMode = Literal["byo", "relay"]


class SetupStatusResponse(BaseModel):
    deployment_mode: DeploymentMode
    setup_required: bool
    web_base_url: str


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
    organization_name: str | None = Field(default=None, max_length=200)
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
    # ADR 0032 — BYO Meta app creds + derived callback the admin whitelists.
    meta_app_id: str
    meta_app_secret_last4: str | None
    meta_oauth_mode: MetaOAuthMode
    meta_oauth_callback_url: str | None
    setup_completed: bool


class InstanceSettingsUpdate(BaseModel):
    """PUT semantics: omitted fields keep their current value; smtp_password
    and meta_app_secret only rotate when a non-empty value is sent (never
    returned back). A changed meta_app_id drops the stored secret — the old
    secret can never pair with a different app."""

    web_base_url: str | None = Field(default=None, max_length=500)
    email_config: SetupEmailConfig | None = None
    meta_app_id: str | None = Field(default=None, max_length=255)
    meta_app_secret: str | None = Field(default=None, max_length=255)

    _check_url = field_validator("web_base_url")(_clean_url)
