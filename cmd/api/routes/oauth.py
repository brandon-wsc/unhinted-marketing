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
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.mcp import oauth
from internal.memory import repos
from internal.memory.database import get_db
from internal.memory.models import User
from schemas.mcp import ConsentRequest

router = APIRouter(prefix="/oauth", tags=["oauth"])


def _oauth_http(exc: oauth.OAuthError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": exc.error, "error_description": exc.description},
    )


@router.get("/authorize")
async def authorize(
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
) -> RedirectResponse:
    """Client opens the browser here; we redirect to the SPA consent page."""
    if response_type != "code":
        raise HTTPException(status_code=400, detail="response_type must be code")
    try:
        request = await oauth.issue_auth_request(
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
        raise _oauth_http(exc) from exc
    return RedirectResponse(oauth.consent_url(request), status_code=302)


@router.get("/authorize/request")
async def authorize_request_details(
    request_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Consent-page data: who is asking, what scopes, which companies apply."""
    from urllib.parse import urlparse

    from internal.memory.models import OAuthAuthRequest

    request = await db.get(OAuthAuthRequest, request_id)
    try:
        oauth.live_request(request)
    except oauth.OAuthError as exc:
        raise _oauth_http(exc) from exc
    return {
        "client_id": request.client_id,
        "client_name": request.client_name or request.client_id,
        "client_host": urlparse(request.client_id).hostname,
        "scopes": request.scope.split(),
        "companies": [
            {"id": str(m.organization_id), "name": m.organization.name}
            for m in user.memberships
            if m.organization.entity_type == "company"
        ],
    }


@router.post("/authorize")
async def consent(
    body: ConsentRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Approve or deny — plain HTTP on the web session, no LLM (ADR 0003)."""
    request_id = body.request_id
    approve = body.approve
    company_id = body.company_id
    if approve and not await repos.user_has_org_access(db, user.id, company_id):
        raise HTTPException(status_code=403, detail="not a member of that company")
    try:
        redirect = await oauth.complete_consent(
            db,
            request_id=request_id,
            user_id=user.id,
            company_id=company_id,
            approve=approve,
        )
        await db.commit()
    except oauth.OAuthError as exc:
        raise _oauth_http(exc) from exc
    return {"redirect": redirect}


@router.post("/token")
async def token(request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
    """Public endpoint — form-encoded per RFC 6749; PKCE is the client auth."""
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
                db, refresh_token=str(form.get("refresh_token") or "")
            )
        else:
            raise oauth.OAuthError("unsupported_grant_type", grant_type or "missing")
        await db.commit()
    except oauth.OAuthError as exc:
        raise _oauth_http(exc) from exc
    return result
