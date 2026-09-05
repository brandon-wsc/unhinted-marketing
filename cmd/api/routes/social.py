"""Org Instagram credentials for Confirm publish (ADR 0022). Editor-only; no raw tokens."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.auth.meta_oauth import (
    CSRF_COOKIE,
    MetaOAuthError,
    exchange_code,
    pending_connect_is_stale,
    start_oauth,
)
from internal.auth.org import require_company_settings_editor
from internal.config import settings
from internal.llm.keys import ByokEncryptionError, encrypt_key, mask_key
from internal.memory import repos
from internal.memory.database import get_db
from internal.memory.models import SocialAccount, User
from internal.memory.repos import (
    cancel_social_oauth,
    delete_social_account,
    list_social_accounts,
    social_account_is_connected,
    upsert_social_account,
)
from schemas.oauth import SocialOAuthInfo
from schemas.social import SocialAccountItem, SocialAccountList, SocialAccountUpsert

router = APIRouter(prefix="/companies/{company_id}/social-accounts", tags=["social"])
oauth_callback_router = APIRouter(prefix="/social", tags=["social"])

OAUTH_POLL_ROUTE = "/api/companies/{company_id}/social-accounts/oauth/status"

_PLATFORMS = frozenset({"instagram"})


def _encrypt_or_503(raw: str) -> str:
    try:
        return encrypt_key(raw)
    except ByokEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _require_platform(platform: str) -> str:
    if platform not in _PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown social platform",
        )
    return platform


def _item(row: SocialAccount) -> SocialAccountItem:
    return SocialAccountItem.model_validate(row)


@router.get("", response_model=SocialAccountList)
async def list_accounts(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SocialAccountList:
    rows = await list_social_accounts(db, company_id)
    return SocialAccountList(
        items=[_item(row) for row in rows if social_account_is_connected(row)]
    )


def _oauth_info(company_id: uuid.UUID, row: SocialAccount | None) -> SocialOAuthInfo:
    if row is not None and row.oauth_connect_state:
        return SocialOAuthInfo(
            status="pending",
            poll_url=OAUTH_POLL_ROUTE.format(company_id=str(company_id)),
        )
    if social_account_is_connected(row):
        return SocialOAuthInfo(status="connected")
    return SocialOAuthInfo(status="not_connected")


@router.get("/oauth/status", response_model=SocialOAuthInfo)
async def oauth_status(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SocialOAuthInfo:
    """Return the org's Meta OAuth connection state (no token material)."""
    row = await repos.get_social_account(db, company_id, "instagram")
    if row is not None and row.oauth_connect_state and pending_connect_is_stale(
        row.oauth_connect_state
    ):
        await cancel_social_oauth(db, company_id, "instagram")
        await db.commit()
        row = await repos.get_social_account(db, company_id, "instagram")
    return _oauth_info(company_id, row)


@router.post("/oauth/start", response_model=SocialOAuthInfo, status_code=status.HTTP_201_CREATED)
async def oauth_start(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SocialOAuthInfo:
    """Start the Meta connect flow. Persists the encrypted pending state and
    returns the authorization URL for a popup / new tab. The double-submit CSRF
    cookie is scoped to the public callback so Meta's redirect carries it back."""
    try:
        started = await start_oauth(db, company_id=company_id)
    except MetaOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message
        ) from exc
    await db.commit()
    response.set_cookie(
        key=CSRF_COOKIE,
        value=started.csrf_token,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        max_age=86400,
        path="/api/social",
    )
    return SocialOAuthInfo(
        status="pending",
        authorization_url=started.authorization_url,
        poll_url=OAUTH_POLL_ROUTE.format(company_id=str(company_id)),
    )


@router.post("/oauth/cancel", response_model=SocialOAuthInfo)
async def oauth_cancel(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SocialOAuthInfo:
    """Abort an in-flight Meta connect (timeout, cancel, or closed popup)."""
    await cancel_social_oauth(db, company_id, "instagram")
    await db.commit()
    row = await repos.get_social_account(db, company_id, "instagram")
    return _oauth_info(company_id, row)


@oauth_callback_router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Backend Meta callback — this exact URL goes into the Meta App Dashboard:
    App Settings → Advanced → Security → Valid OAuth Redirect URIs."""
    if error:
        await repos.clear_social_oauth_state_for_state(db, state)
        await db.commit()
        return _oauth_redirect(detail="access_denied")

    if not code or not state:
        await repos.clear_social_oauth_state_for_state(db, state)
        await db.commit()
        return _oauth_redirect(detail="meta_oauth_missing_params")

    try:
        result = await exchange_code(
            db,
            code=code,
            state=state,
            csrf_token=request.cookies.get(CSRF_COOKIE),
        )
    except MetaOAuthError as exc:
        await repos.clear_social_oauth_state_for_state(db, state)
        await db.commit()
        return _oauth_redirect(detail=exc.message)

    await db.commit()
    return _oauth_redirect(
        detail="ok",
        missing_scopes=",".join(result.missing_scopes) if result.missing_scopes else None,
        ig_user_id=result.ig_user_id,
    )


def _oauth_redirect(
    *,
    detail: str,
    missing_scopes: str | None = None,
    ig_user_id: str | None = None,
) -> RedirectResponse:
    from urllib.parse import urlencode

    base = (settings.meta_oauth_success_url or "").strip() or (settings.web_base_url or "").strip()
    params: dict[str, str] = {"oauth": "done", "status": detail}
    if missing_scopes:
        params["missing_scopes"] = missing_scopes
    if ig_user_id:
        params["ig_user_id"] = ig_user_id
    return RedirectResponse(url=f"{base}?{urlencode(params)}")


@router.put("/{platform}", response_model=SocialAccountItem)
async def upsert_account(
    platform: str,
    body: SocialAccountUpsert,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SocialAccountItem:
    _require_platform(platform)
    row = await upsert_social_account(
        db,
        company_id=company_id,
        platform=platform,
        ig_user_id=body.ig_user_id,
        access_token_encrypted=_encrypt_or_503(body.access_token),
        token_last4=mask_key(body.access_token),
        expires_at=_aware(body.expires_at),
        created_by=user.id,
    )
    await db.commit()
    await db.refresh(row)
    return _item(row)


@router.delete("/{platform}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_account(
    platform: str,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    _require_platform(platform)
    deleted = await delete_social_account(db, company_id, platform)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="social_account_not_connected",
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
