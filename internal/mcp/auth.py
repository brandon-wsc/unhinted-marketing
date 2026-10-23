"""Bearer auth for the MCP endpoint (ADR 0051 §4).

Verifies the ``mcp_access`` JWT, then re-checks the live grant, membership
and ``is_active`` on every call. Identity never comes from tool arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.service import get_user_with_memberships
from internal.mcp.tokens import (
    MCP_PATH,
    McpAccessClaims,
    McpTokenError,
    verify_mcp_access_token,
)
from internal.memory import repos
from internal.memory.database import get_db
from internal.memory.models import OAuthGrant, User

bearer_scheme = HTTPBearer(auto_error=False)


def _prm_url() -> str:
    from internal.instance.config import get_snapshot

    return f"{get_snapshot().web_base_url}/.well-known/oauth-protected-resource{MCP_PATH}"


def challenge_header(*, scope: str | None = None, error: str | None = None) -> str:
    """WWW-Authenticate value — PRM pointer plus optional step-up fields."""
    parts = [f'resource_metadata="{_prm_url()}"']
    if error:
        parts.insert(0, f'error="{error}"')
    if scope:
        parts.append(f'scope="{scope}"')
    return f"Bearer {' '.join(parts)}"


def auth_challenge() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": challenge_header()},
    )


def insufficient_scope(scope: str) -> HTTPException:
    """403 + scope hint — the client's cue to re-authorize (step-up, §5)."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="insufficient_scope",
        headers={"WWW-Authenticate": challenge_header(scope=scope, error="insufficient_scope")},
    )


@dataclass
class McpContext:
    """Authenticated caller: token claims plus the live grant row."""

    claims: McpAccessClaims
    grant: OAuthGrant
    user: User

    @property
    def scopes(self) -> set[str]:
        return set(self.grant.scopes or [])


async def get_mcp_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> McpContext:
    from internal.mcp import grants as grant_repo

    if not credentials or credentials.scheme.lower() != "bearer":
        raise auth_challenge()
    try:
        claims = verify_mcp_access_token(credentials.credentials)
    except McpTokenError as exc:
        raise auth_challenge() from exc

    grant = await grant_repo.get_active_grant(db, claims.grant_id)
    if grant is None or grant.user_id != claims.user_id or grant.company_id != claims.company_id:
        raise auth_challenge()

    user = await get_user_with_memberships(db, claims.user_id)
    if user is None or not user.is_active:
        raise auth_challenge()
    if not await repos.user_has_org_access(db, claims.user_id, claims.company_id):
        raise auth_challenge()

    await grant_repo.touch_grant(db, grant)
    return McpContext(claims=claims, grant=grant, user=user)
