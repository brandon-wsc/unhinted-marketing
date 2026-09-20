"""Org Instagram credentials for Confirm publish (ADR 0022). Editor-only; no raw tokens."""

from __future__ import annotations

import logging
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
    meta_platform_callback_urls,
    oauth_callback_url,
    oauth_configured,
    pending_connect_is_stale,
    process_data_deletion,
    process_deauthorize,
    process_relay_platform_event,
    redeem_relay_ticket,
    start_oauth,
    verify_data_deletion_code,
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
from schemas.oauth import (
    MetaDataDeletionResponse,
    MetaDataDeletionStatus,
    MetaRelayEvent,
    MetaRelayResult,
    SocialOAuthInfo,
)
from schemas.social import SocialAccountItem, SocialAccountList, SocialAccountUpsert

router = APIRouter(prefix="/companies/{company_id}/social-accounts", tags=["social"])
oauth_callback_router = APIRouter(prefix="/social", tags=["social"])
logger = logging.getLogger(__name__)

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
    from internal.instance.config import get_snapshot as get_instance_snapshot

    config = {
        "configured": oauth_configured(),
        "callback_url": oauth_callback_url(),
        "mode": get_instance_snapshot().meta_oauth_mode,
        **meta_platform_callback_urls(),
    }
    if row is not None and row.oauth_connect_state:
        return SocialOAuthInfo(
            status="pending",
            poll_url=OAUTH_POLL_ROUTE.format(company_id=str(company_id)),
            **config,
        )
    if social_account_is_connected(row):
        return SocialOAuthInfo(status="connected", **config)
    return SocialOAuthInfo(status="not_connected", **config)


@router.get("/oauth/status", response_model=SocialOAuthInfo)
async def oauth_status(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SocialOAuthInfo:
    """Return the org's Instagram Login connection state (no token material)."""
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
    from internal.instance.config import get_snapshot as get_instance_snapshot

    return SocialOAuthInfo(
        status="pending",
        authorization_url=started.authorization_url,
        poll_url=OAUTH_POLL_ROUTE.format(company_id=str(company_id)),
        configured=True,
        callback_url=oauth_callback_url(),
        mode=get_instance_snapshot().meta_oauth_mode,
        **meta_platform_callback_urls(),
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
    """Backend Instagram Login callback — this exact URL goes into the Meta
    App Dashboard → Instagram → Valid OAuth Redirect URIs."""
    if error:
        logger.warning("meta oauth callback denied: %s", error)
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
        logger.warning("meta oauth callback failed: %s", exc.message)
        await repos.clear_social_oauth_state_for_state(db, state)
        await db.commit()
        return _oauth_redirect(detail=exc.message)

    await db.commit()
    logger.info("meta oauth callback ok ig_user_id=%s", result.ig_user_id)
    return _oauth_redirect(
        detail="ok",
        missing_scopes=",".join(result.missing_scopes) if result.missing_scopes else None,
        ig_user_id=result.ig_user_id,
    )


@oauth_callback_router.get("/oauth/relay-finish")
async def oauth_relay_finish(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    ticket: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Relay-mode landing (ADR 0032 §3) — the vendor relay already exchanged
    the Meta code; it 302s the browser here with a one-time ticket we redeem
    server-to-server. Same CSRF/state gates as the BYO callback."""
    if error:
        logger.warning("meta oauth relay finish failed upstream: %s", error)
        await repos.clear_social_oauth_state_for_state(db, state)
        await db.commit()
        return _oauth_redirect(detail=error)

    if not ticket or not state:
        await repos.clear_social_oauth_state_for_state(db, state)
        await db.commit()
        return _oauth_redirect(detail="meta_oauth_missing_params")

    try:
        result = await redeem_relay_ticket(
            db,
            ticket=ticket,
            state=state,
            csrf_token=request.cookies.get(CSRF_COOKIE),
        )
    except MetaOAuthError as exc:
        logger.warning("meta oauth relay finish failed: %s", exc.message)
        await repos.clear_social_oauth_state_for_state(db, state)
        await db.commit()
        return _oauth_redirect(detail=exc.message)

    await db.commit()
    logger.info("meta oauth relay finish ok ig_user_id=%s", result.ig_user_id)
    return _oauth_redirect(
        detail="ok",
        missing_scopes=",".join(result.missing_scopes) if result.missing_scopes else None,
        ig_user_id=result.ig_user_id,
    )


@oauth_callback_router.post("/meta/deauthorize")
async def meta_deauthorize(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Meta deauthorize callback (ADR 0033) — user removed the app in their
    Instagram settings. Meta POSTs a form ``signed_request``; the signature
    (HMAC-SHA256 with the app secret) is the only auth on this public route."""
    form = await request.form()
    try:
        ig_user_id = await process_deauthorize(
            db, signed_request=str(form.get("signed_request") or "")
        )
    except MetaOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message
        ) from exc
    await db.commit()
    logger.info("meta deauthorize ok ig_user_id=%s", ig_user_id)
    return Response(status_code=status.HTTP_200_OK)


@oauth_callback_router.post("/meta/data-deletion", response_model=MetaDataDeletionResponse)
async def meta_data_deletion(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MetaDataDeletionResponse:
    """Meta data-deletion callback (ADR 0033) — delete the IG user's stored
    connection, then answer the JSON Meta expects: a status URL plus a
    confirmation code."""
    form = await request.form()
    try:
        code, url = await process_data_deletion(
            db, signed_request=str(form.get("signed_request") or "")
        )
    except MetaOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message
        ) from exc
    await db.commit()
    logger.info("meta data deletion ok")
    return MetaDataDeletionResponse(url=url, confirmation_code=code)


@oauth_callback_router.get(
    "/meta/data-deletion/{code}", response_model=MetaDataDeletionStatus
)
async def meta_data_deletion_status(code: str) -> MetaDataDeletionStatus:
    """User-facing status page Meta shows next to the confirmation code.
    Deletion already ran before we answered Meta, so a valid code is always
    ``completed``."""
    if verify_data_deletion_code(code) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown confirmation code"
        )
    return MetaDataDeletionStatus(confirmation_code=code)


@oauth_callback_router.post("/meta/relay", response_model=MetaRelayResult)
async def meta_relay_event(
    body: MetaRelayEvent,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MetaRelayResult:
    """Relay-forwarded platform event (ADR 0033 §3) — the vendor relay verified
    Meta's signed_request and re-signed this with our registry slug."""
    try:
        result = await process_relay_platform_event(
            db, kind=body.kind, ig_user_id=body.ig_user_id, sig=body.sig
        )
    except MetaOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message
        ) from exc
    await db.commit()
    logger.info("meta relay event %s ok ig_user_id=%s", body.kind, body.ig_user_id)
    return MetaRelayResult(**result)


def _oauth_redirect(
    *,
    detail: str,
    missing_scopes: str | None = None,
    ig_user_id: str | None = None,
) -> RedirectResponse:
    from urllib.parse import urlencode

    from internal.instance.config import get_snapshot as get_instance_snapshot

    custom = (settings.meta_oauth_success_url or "").strip()
    base = custom or (get_instance_snapshot().web_base_url or "").strip()
    params: dict[str, str] = {"oauth": "done", "status": detail}
    if not custom:
        params["tab"] = "instagram"
        if not base.rstrip("/").endswith("/settings"):
            base = f"{base.rstrip('/')}/settings"
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
