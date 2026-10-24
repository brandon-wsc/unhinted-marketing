"""OAuth 2.1 + PKCE flow for MCP clients (ADR 0051 §2–§4).

The pending-request → consent → code → token chain. Codes and refresh
tokens are single-use and stored hashed; refresh rotates inside a family
and dies with the grant. ``resource`` (RFC 8707) is checked at both ends.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.jwt import generate_refresh_token, hash_refresh_token
from internal.instance.config import get_snapshot
from internal.mcp.clients import (
    ClientMetadataError,
    fetch_client_metadata,
    redirect_uri_allowed,
    validate_client_id,
)
from internal.mcp.grants import KNOWN_SCOPES, get_active_grant
from internal.mcp.tokens import create_mcp_access_token, mcp_resource_url
from internal.memory.models import (
    OAuthAuthRequest,
    OAuthCode,
    OAuthGrant,
    OAuthRefreshToken,
)
from schemas.mcp import OAuthTokenResponse

AUTH_REQUEST_TTL = timedelta(minutes=10)
AUTH_CODE_TTL = timedelta(seconds=60)
REFRESH_TTL = timedelta(days=30)
# Double-submit cookie set on the /authorize redirect: only the browser that
# started the flow may read or answer its consent request (§3).
REQUEST_COOKIE = "mcp_oauth_request"
# `images:generate` is opt-in at consent (the only step-up scope today).
STEP_UP_SCOPES = frozenset({"images:generate"})
# Scopes the PRM advertises.
DEFAULT_SCOPES = sorted(KNOWN_SCOPES - STEP_UP_SCOPES)


class OAuthError(Exception):
    """OAuth-spec error; ``error`` is the RFC 6749 code."""

    def __init__(self, error: str, description: str) -> None:
        self.error = error
        self.description = description
        super().__init__(f"{error}: {description}")


def pkce_verifier_matches(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return secrets.compare_digest(computed, challenge)


def parse_scope(scope: str | None) -> list[str]:
    """Requested scopes; absent → the PRM's default set. Unknown → invalid_scope."""
    if not scope or not scope.strip():
        return list(DEFAULT_SCOPES)
    requested = [s for s in scope.split() if s]
    unknown = set(requested) - KNOWN_SCOPES
    if unknown:
        raise OAuthError("invalid_scope", f"unknown scopes: {sorted(unknown)}")
    return sorted(set(requested))


async def sweep_expired_oauth_rows(db: AsyncSession) -> None:
    """Drop dead pending rows — authorize requests and single-use codes."""
    now = datetime.now(UTC)
    await db.execute(delete(OAuthAuthRequest).where(OAuthAuthRequest.expires_at < now))
    await db.execute(delete(OAuthCode).where(OAuthCode.expires_at < now))


async def issue_auth_request(
    db: AsyncSession,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scope: str | None,
    code_challenge: str | None,
    code_challenge_method: str | None,
    resource: str | None,
) -> OAuthAuthRequest:
    """Validate the /authorize query; a failure surfaces as an OAuth error."""
    await sweep_expired_oauth_rows(db)
    try:
        clean_client_id = await validate_client_id(client_id)
    except ClientMetadataError as exc:
        raise OAuthError("invalid_client", exc.message) from exc
    try:
        doc = await fetch_client_metadata(clean_client_id)
    except ClientMetadataError as exc:
        raise OAuthError("invalid_client", exc.message) from exc
    if not redirect_uri_allowed(doc, redirect_uri or ""):
        raise OAuthError("invalid_request", "redirect_uri not in client metadata")
    if (code_challenge_method or "").upper() != "S256" or not code_challenge:
        raise OAuthError("invalid_request", "PKCE S256 is required")
    if (resource or "").strip() != mcp_resource_url():
        raise OAuthError("invalid_target", "resource must be the MCP endpoint")

    request = OAuthAuthRequest(
        client_id=clean_client_id,
        client_name=str(doc.get("client_name") or ""),
        redirect_uri=redirect_uri,
        scope=" ".join(parse_scope(scope)),
        state=(state or "")[:500],
        code_challenge=code_challenge,
        resource=mcp_resource_url(),
        expires_at=datetime.now(UTC) + AUTH_REQUEST_TTL,
    )
    db.add(request)
    await db.flush()
    return request


def consent_url(request: OAuthAuthRequest) -> str:
    """The SPA page the authorize endpoint redirects to."""
    from internal.instance.config import get_snapshot

    return f"{get_snapshot().web_base_url}/oauth/consent?request_id={request.id}"


def live_request(request: OAuthAuthRequest | None) -> OAuthAuthRequest:
    if request is None or request.consumed_at is not None or request.expires_at < datetime.now(UTC):
        raise OAuthError("invalid_request", "authorization request expired or unknown")
    return request


async def complete_consent(
    db: AsyncSession,
    *,
    request_id: uuid.UUID,
    user_id: uuid.UUID,
    company_id: uuid.UUID | None,
    approve: bool,
) -> str:
    """Consent → redirect URL with code+state+iss (RFC 9207) or error."""
    # Atomic consume — a second concurrent consent finds the row already
    # stamped instead of racing into a duplicate code/grant upsert.
    request = await db.scalar(
        update(OAuthAuthRequest)
        .where(
            OAuthAuthRequest.id == request_id,
            OAuthAuthRequest.consumed_at.is_(None),
            OAuthAuthRequest.expires_at > datetime.now(UTC),
        )
        .values(consumed_at=datetime.now(UTC))
        .returning(OAuthAuthRequest)
    )
    if request is None:
        raise OAuthError("invalid_request", "authorization request expired or unknown")
    query = {"state": request.state, "iss": get_snapshot().web_base_url}
    if not approve:
        query["error"] = "access_denied"
        return f"{request.redirect_uri}?{urlencode(query)}"

    code = secrets.token_urlsafe(32)
    db.add(
        OAuthCode(
            code_hash=hash_refresh_token(code),
            user_id=user_id,
            company_id=company_id,
            client_id=request.client_id,
            redirect_uri=request.redirect_uri,
            scope=request.scope,
            resource=request.resource,
            code_challenge=request.code_challenge,
            expires_at=datetime.now(UTC) + AUTH_CODE_TTL,
        )
    )
    query["code"] = code
    return f"{request.redirect_uri}?{urlencode(query)}"


async def _upsert_grant(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    client_id: str,
    client_name: str,
    scopes: list[str],
) -> OAuthGrant:
    """Re-consent refreshes the existing grant (uq_oauth_grant) instead of duplicating."""
    grant = await db.scalar(
        select(OAuthGrant).where(
            OAuthGrant.user_id == user_id,
            OAuthGrant.client_id == client_id,
            OAuthGrant.company_id == company_id,
        )
    )
    if grant is not None and grant.revoked_at is not None:
        # A revoked grant must never come back: tokens bound to its id stay
        # dead. Delete so the unique slot frees, then issue a fresh grant.
        await db.delete(grant)
        await db.flush()
        grant = None
    if grant is None:
        grant = OAuthGrant(
            user_id=user_id,
            company_id=company_id,
            client_id=client_id,
            client_name=client_name,
            scopes=scopes,
        )
        db.add(grant)
    else:
        grant.client_name = client_name
        grant.scopes = scopes
    await db.flush()
    return grant


async def _mint_refresh(db: AsyncSession, grant: OAuthGrant) -> str:
    token = generate_refresh_token()
    db.add(
        OAuthRefreshToken(
            grant_id=grant.id,
            token_hash=hash_refresh_token(token),
            family_id=uuid.uuid4(),
            expires_at=datetime.now(UTC) + REFRESH_TTL,
        )
    )
    return token


def _token_response(
    grant: OAuthGrant, access: str, expires: datetime, refresh: str
) -> OAuthTokenResponse:
    return OAuthTokenResponse(
        access_token=access,
        expires_in=max(0, int((expires - datetime.now(UTC)).total_seconds())),
        refresh_token=refresh,
        scope=" ".join(grant.scopes or []),
    )


async def exchange_code(
    db: AsyncSession,
    *,
    code: str,
    redirect_uri: str,
    client_id: str,
    code_verifier: str | None,
    resource: str | None,
) -> OAuthTokenResponse:
    row = await db.scalar(select(OAuthCode).where(OAuthCode.code_hash == hash_refresh_token(code)))
    if (
        row is None
        or row.consumed_at is not None
        or row.expires_at < datetime.now(UTC)
        or row.client_id != client_id
        or row.redirect_uri != redirect_uri
        or not code_verifier
        or not pkce_verifier_matches(code_verifier, row.code_challenge)
    ):
        raise OAuthError("invalid_grant", "authorization code failed verification")
    # RFC 8707 — when the client omits `resource` at the token call, the
    # code's bound value stands; a supplied one must still match.
    if resource is not None and str(resource).strip() != row.resource:
        raise OAuthError("invalid_target", "resource does not match the code")
    consumed = await db.scalar(
        update(OAuthCode)
        .where(OAuthCode.id == row.id, OAuthCode.consumed_at.is_(None))
        .values(consumed_at=datetime.now(UTC))
        .returning(OAuthCode)
    )
    if consumed is None:
        raise OAuthError("invalid_grant", "authorization code already used")
    row = consumed

    try:
        client_doc = await fetch_client_metadata(client_id)
        client_name = str(client_doc.get("client_name") or "")
    except ClientMetadataError:
        client_name = ""
    grant = await _upsert_grant(
        db,
        user_id=row.user_id,
        company_id=row.company_id,
        client_id=client_id,
        client_name=client_name,
        scopes=row.scope.split(),
    )
    access, expires = create_mcp_access_token(grant)
    refresh = await _mint_refresh(db, grant)
    return _token_response(grant, access, expires, refresh)


async def rotate_refresh(
    db: AsyncSession, *, refresh_token: str, client_id: str | None
) -> OAuthTokenResponse:
    # OAuth 2.1 — an unauthenticated (public) client must send client_id, or
    # the refresh token is not bound to anyone.
    if not client_id:
        raise OAuthError("invalid_request", "client_id is required")
    row = await db.scalar(
        select(OAuthRefreshToken).where(
            OAuthRefreshToken.token_hash == hash_refresh_token(refresh_token)
        )
    )
    if row is None or row.expires_at < datetime.now(UTC):
        raise OAuthError("invalid_grant", "refresh token invalid")
    if row.revoked_at is not None:
        # Reuse of a rotated-out token (OAuth 2.1 §6.1): someone has a stale
        # copy — kill the whole family, forcing a fresh authorize.
        await db.execute(
            update(OAuthRefreshToken)
            .where(
                OAuthRefreshToken.family_id == row.family_id,
                OAuthRefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        raise OAuthError("invalid_grant", "refresh token reuse detected")
    grant = await get_active_grant(db, row.grant_id)
    if grant is None:
        raise OAuthError("invalid_grant", "grant revoked")
    if grant.client_id != client_id:
        raise OAuthError("invalid_client", "client_id does not match the grant")
    row.revoked_at = datetime.now(UTC)

    access, expires = create_mcp_access_token(grant)
    new_token = generate_refresh_token()
    db.add(
        OAuthRefreshToken(
            grant_id=grant.id,
            token_hash=hash_refresh_token(new_token),
            family_id=row.family_id,
            expires_at=datetime.now(UTC) + REFRESH_TTL,
        )
    )
    return _token_response(grant, access, expires, new_token)
