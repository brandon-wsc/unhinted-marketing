from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.auth.invites import hash_invite_token, normalize_invite_email
from internal.auth.rate_limit import enforce_auth_rate_limit
from internal.auth.service import (
    AuthError,
    get_user_with_memberships,
    login_user,
    logout_user,
    refresh_session,
    register_user,
)
from internal.config import settings
from internal.memory import repos
from internal.memory.database import get_db
from internal.memory.models import User
from schemas.auth import (
    LoginRequest,
    MessageResponse,
    OrganizationSummary,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
# Cookie Path must match the mounted auth routes (ADR 0006).
REFRESH_COOKIE_PATH = "/api/auth"


def _user_response(user: User) -> UserResponse:
    orgs = [
        OrganizationSummary(
            id=m.organization.id,
            name=m.organization.name,
            slug=m.organization.slug,
            role=m.role,
        )
        for m in user.memberships
    ]
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        platform_level=user.platform_level,
        created_at=user.created_at,
        organizations=orgs,
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        max_age=settings.jwt_refresh_expire_days * 86400,
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


def _token_response(
    user: User, access_token: str, refresh_token: str, response: Response
) -> TokenResponse:
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(
        access_token=access_token,
        expires_in=settings.jwt_access_expire_minutes * 60,
        user=_user_response(user),
    )


async def _invite_allows_registration(
    db: AsyncSession, token: str | None, email: str
) -> bool:
    """ADR 0026 — on-prem register requires a pending invite for this email."""
    if not token:
        return False
    invite = await repos.get_org_invite_by_token_hash(db, hash_invite_token(token))
    if not invite or invite.revoked_at or invite.accepted_at:
        return False
    if invite.expires_at < datetime.now(UTC):
        return False
    return normalize_invite_email(email) == invite.email


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    enforce_auth_rate_limit(request, bucket="register")
    if settings.deployment_mode == "onprem":
        instance = await repos.get_instance_settings(db)
        if instance is None or instance.setup_completed_at is None:
            raise HTTPException(status_code=403, detail="setup_required")
        if not await _invite_allows_registration(db, body.invite_token, body.email):
            raise HTTPException(status_code=403, detail="invite_required")
    try:
        user, access, refresh = await register_user(
            db,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            organization_name=body.organization_name,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    user = await get_user_with_memberships(db, user.id)
    assert user is not None
    return _token_response(user, access, refresh, response)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    enforce_auth_rate_limit(request, bucket="login")
    try:
        user, access, refresh = await login_user(db, email=body.email, password=body.password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    user = await get_user_with_memberships(db, user.id)
    assert user is not None
    return _token_response(user, access, refresh, response)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    enforce_auth_rate_limit(request, bucket="refresh")
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="Refresh token missing")
    try:
        user, access, new_refresh = await refresh_session(db, raw_refresh_token=raw)
    except AuthError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    user = await get_user_with_memberships(db, user.id)
    assert user is not None
    return _token_response(user, access, new_refresh, response)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        await logout_user(db, raw_refresh_token=raw)
    _clear_refresh_cookie(response)
    return MessageResponse(message="Logged out")


@router.get("/me", response_model=UserResponse)
async def me(user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return _user_response(user)
