"""On-prem first-run setup + instance settings (ADR 0026).

`POST /api/setup` claims the first user (platform SUPERADMIN + org owner) and
seals the deployment by stamping `instance_settings.setup_completed_at`. The
row is locked `FOR UPDATE` so a concurrent second claim loses cleanly.
`GET/PUT /api/instance/settings` is the platform-gated post-setup edit path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cmd.api.routes.auth import _token_response
from internal.auth.rate_limit import enforce_auth_rate_limit
from internal.auth.roles import PlatformLevel, require_platform_level
from internal.auth.service import AuthError, get_user_with_memberships, register_user
from internal.config import settings
from internal.instance.config import load_snapshot
from internal.llm.keys import ByokEncryptionError, encrypt_key, mask_key
from internal.memory import repos
from internal.memory.database import get_db
from internal.memory.models import InstanceSettings, User
from schemas.auth import TokenResponse
from schemas.setup import (
    InstanceSettingsResponse,
    InstanceSettingsUpdate,
    SetupEmailConfig,
    SetupRequest,
    SetupStatusResponse,
)

router = APIRouter(tags=["setup"])

AdminRead = Annotated[User, Depends(require_platform_level(PlatformLevel.ADMIN))]
SuperAdmin = Annotated[User, Depends(require_platform_level(PlatformLevel.SUPERADMIN))]


def _env_llm_configured() -> bool:
    return bool(
        settings.openai_api_key
        or settings.anthropic_api_key
        or settings.gemini_api_key
        or settings.vertex_ai_api_key
        or settings.google_api_key
        or settings.llm_api_base
    )


async def _setup_pending(db: AsyncSession) -> bool:
    row = await repos.get_instance_settings(db)
    return row is None or row.setup_completed_at is None


def _settings_out(row: InstanceSettings | None) -> InstanceSettingsResponse:
    if row is None:
        return InstanceSettingsResponse(
            web_base_url="",
            email_backend="link",
            email_from="",
            smtp_host="",
            smtp_port=587,
            smtp_user="",
            smtp_password_last4=None,
            smtp_tls=True,
            setup_completed=False,
        )
    return InstanceSettingsResponse(
        web_base_url=row.web_base_url or "",
        email_backend=row.email_backend,  # type: ignore[arg-type]
        email_from=row.email_from or "",
        smtp_host=row.smtp_host or "",
        smtp_port=row.smtp_port or 587,
        smtp_user=row.smtp_user or "",
        smtp_password_last4=row.smtp_password_last4,
        smtp_tls=row.smtp_tls,
        setup_completed=row.setup_completed_at is not None,
    )


def _email_fields(email: SetupEmailConfig) -> dict:
    fields: dict = {
        "email_backend": email.backend,
        "email_from": email.email_from or None,
        "smtp_host": email.smtp_host or None,
        "smtp_port": email.smtp_port,
        "smtp_user": email.smtp_user or None,
        "smtp_tls": email.smtp_tls,
    }
    if email.smtp_password:
        try:
            fields["smtp_password_encrypted"] = encrypt_key(email.smtp_password)
            fields["smtp_password_last4"] = mask_key(email.smtp_password)
        except ByokEncryptionError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc
    return fields


@router.get("/setup/status", response_model=SetupStatusResponse)
async def setup_status(db: Annotated[AsyncSession, Depends(get_db)]) -> SetupStatusResponse:
    snap = await load_snapshot(db)
    pending = await _setup_pending(db)
    return SetupStatusResponse(
        deployment_mode=settings.deployment_mode,
        setup_required=settings.deployment_mode == "onprem" and pending,
        web_base_url=snap.web_base_url,
        env_llm_configured=_env_llm_configured(),
        env_smtp_configured=bool(settings.smtp_host),
    )


@router.post("/setup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def run_setup(
    body: SetupRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    if settings.deployment_mode != "onprem":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    enforce_auth_rate_limit(request, bucket="register")

    # Row lock serializes first-user claims; a missing row is claimed by insert.
    row = await db.scalar(
        select(InstanceSettings).where(InstanceSettings.id == 1).with_for_update()
    )
    if row is not None and row.setup_completed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Setup already completed"
        )

    fields: dict = {"setup_completed_at": datetime.now(UTC)}
    if body.web_base_url:
        fields["web_base_url"] = body.web_base_url
    if body.email_config is not None:
        fields.update(_email_fields(body.email_config))
    try:
        await repos.upsert_instance_settings(db, **fields)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Setup already completed"
        ) from exc

    try:
        user, access, refresh = await register_user(
            db,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            organization_name=body.organization_name,
            platform_level=int(PlatformLevel.SUPERADMIN),
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    await load_snapshot(db)

    user = await get_user_with_memberships(db, user.id)
    assert user is not None
    return _token_response(user, access, refresh, response)


@router.get("/instance/settings", response_model=InstanceSettingsResponse)
async def get_instance_settings(
    _admin: AdminRead,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InstanceSettingsResponse:
    return _settings_out(await repos.get_instance_settings(db))


@router.put("/instance/settings", response_model=InstanceSettingsResponse)
async def put_instance_settings(
    body: InstanceSettingsUpdate,
    _super: SuperAdmin,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InstanceSettingsResponse:
    fields: dict = {}
    if body.web_base_url is not None:
        fields["web_base_url"] = body.web_base_url
    if body.email_config is not None:
        fields.update(_email_fields(body.email_config))
    if fields:
        row = await repos.upsert_instance_settings(db, **fields)
    else:
        row = await repos.get_instance_settings(db)
    await db.commit()
    await load_snapshot(db)
    return _settings_out(row)
