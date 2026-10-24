"""OAuth authorization-server endpoints (ADR 0051 §2–§4).

``GET /api/oauth/authorize`` validates the client + PKCE + resource, then
302s to the SPA consent page. Approve/deny is plain HTTP over the existing
web session. ``POST /api/oauth/token`` is the public, unauthenticated
code-exchange / refresh endpoint.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.auth.rate_limit import enforce_auth_rate_limit
from internal.config import settings
from internal.mcp import oauth
from internal.memory import repos
from internal.memory.database import get_db
from internal.memory.models import User
from schemas.mcp import (
    ConsentDetails,
    ConsentDetailsCompany,
    ConsentRequest,
    ConsentResult,
    OAuthErrorBody,
)

router = APIRouter(prefix="/oauth", tags=["oauth"])


_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _oauth_error(exc: oauth.OAuthError) -> JSONResponse:
    """RFC 6749 §5.2 — the error code lives at the top level, not in detail."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=OAuthErrorBody(error=exc.error, error_description=exc.description).model_dump(),
        headers=_NO_STORE,
    )


def _require_flow_cookie(http_request: Request, request_id: uuid.UUID) -> None:
    """The pending request is only visible to the browser that started it."""
    if http_request.cookies.get(oauth.REQUEST_COOKIE) != str(request_id):
        raise HTTPException(status_code=404, detail="Authorization request not found")


@router.get("/authorize", response_model=None)
async def authorize(
    http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    *,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    response_type: str = "code",
    state: str = "",
    scope: str | None = None,
    resource: str | None = None,
) -> RedirectResponse | JSONResponse:
    """Client opens the browser here; we redirect to the SPA consent page."""
    # Unauthenticated + outbound metadata fetch — keep the window tight.
    enforce_auth_rate_limit(http_request, bucket="oauth_authorize")
    if response_type != "code":
        raise HTTPException(status_code=400, detail="response_type must be code")
    try:
        auth_request = await oauth.issue_auth_request(
            db,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            resource=resource,
        )
        await db.commit()
    except oauth.OAuthError as exc:
        return _oauth_error(exc)
    response = RedirectResponse(oauth.consent_url(auth_request), status_code=302)
    response.set_cookie(
        key=oauth.REQUEST_COOKIE,
        value=str(auth_request.id),
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        max_age=int(oauth.AUTH_REQUEST_TTL.total_seconds()),
        path="/api/oauth",
    )
    return response


@router.get("/authorize/request", response_model=None)
async def authorize_request_details(
    request_id: uuid.UUID,
    http_request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConsentDetails | JSONResponse:
    """Consent-page data: who is asking, what scopes, which companies apply."""
    from urllib.parse import urlparse

    from internal.memory.models import OAuthAuthRequest

    _require_flow_cookie(http_request, request_id)
    request = await db.get(OAuthAuthRequest, request_id)
    try:
        oauth.live_request(request)
    except oauth.OAuthError as exc:
        return _oauth_error(exc)
    requested = request.scope.split()
    return ConsentDetails(
        client_id=request.client_id,
        client_name=request.client_name or request.client_id,
        client_host=urlparse(request.client_id).hostname,
        scopes=requested,
        step_up_scopes=oauth.step_up_scopes_for(requested),
        companies=[
            ConsentDetailsCompany(id=m.organization_id, name=m.organization.name)
            for m in user.memberships
            if m.organization.entity_type == "company"
        ],
    )


@router.post("/authorize", response_model=None)
async def consent(
    body: ConsentRequest,
    http_request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConsentResult | JSONResponse:
    """Approve or deny — plain HTTP on the web session, no LLM (ADR 0003)."""
    request_id = body.request_id
    _require_flow_cookie(http_request, request_id)
    approve = body.approve
    company_id = body.company_id
    if approve and company_id is None:
        raise HTTPException(status_code=400, detail="company_id is required to approve")
    # Same shape as the GET list: grants bind companies only, so a non-company
    # org id must not be approvable through the POST even if membership exists.
    if approve and (
        await repos.get_company(db, company_id) is None
        or not await repos.user_has_org_access(db, user.id, company_id)
    ):
        raise HTTPException(status_code=403, detail="not a member of that company")
    try:
        redirect = await oauth.complete_consent(
            db,
            request_id=request_id,
            user_id=user.id,
            company_id=company_id,
            approve=approve,
            extra_scopes=body.extra_scopes,
        )
        await db.commit()
    except oauth.OAuthError as exc:
        return _oauth_error(exc)
    return ConsentResult(redirect=redirect)


@router.post("/token", response_model=None)
async def token(request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> JSONResponse:
    """Public endpoint — form-encoded per RFC 6749; PKCE is the client auth."""
    enforce_auth_rate_limit(request, bucket="oauth_token")
    form = await request.form()
    grant_type = str(form.get("grant_type") or "")
    try:
        if grant_type == "authorization_code":
            result = await oauth.exchange_code(
                db,
                code=str(form.get("code") or ""),
                redirect_uri=str(form.get("redirect_uri") or ""),
                client_id=str(form.get("client_id") or ""),
                code_verifier=form.get("code_verifier"),
                resource=form.get("resource"),
            )
        elif grant_type == "refresh_token":
            result = await oauth.rotate_refresh(
                db,
                refresh_token=str(form.get("refresh_token") or ""),
                client_id=form.get("client_id") or None,
            )
        else:
            raise oauth.OAuthError("unsupported_grant_type", grant_type or "missing")
        await db.commit()
    except oauth.OAuthError as exc:
        return _oauth_error(exc)
    return JSONResponse(result.model_dump(), headers=_NO_STORE)
