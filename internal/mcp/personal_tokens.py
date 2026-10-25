"""Personal access tokens for headless MCP clients (ADR 0056).

A PAT is a self-issued grant: minting creates an ``oauth_grants`` row whose
``client_id`` is the per-token URN, plus a ``mcp_personal_tokens`` row that
resolves ``sha256(token)`` → grant. Revocation, membership checks and
``last_used_at`` all ride the grant, so nothing here duplicates ADR 0051's
live re-checks.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.jwt import hash_refresh_token
from internal.memory.models import McpPersonalToken, OAuthGrant

PAT_PREFIX = "unh_"
# ``client_id`` on the backing grant — also how ConnectedApp rows are tagged
# ``kind: "pat"`` without a schema change on oauth_grants.
PAT_CLIENT_ID_PREFIX = "urn:unhinted:pat:"
MAX_LIVE_PATS_PER_USER = 20
_TOKEN_PREFIX_LEN = 12


def is_pat(token: str) -> bool:
    return token.startswith(PAT_PREFIX)


def _generate_token() -> str:
    return PAT_PREFIX + secrets.token_urlsafe(36)


def is_pat_client_id(client_id: str) -> bool:
    return client_id.startswith(PAT_CLIENT_ID_PREFIX)


async def mint_pat(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    name: str,
    scopes: list[str],
    expires_at: datetime | None,
) -> tuple[OAuthGrant, McpPersonalToken, str]:
    """Create the grant + token row; callers commit. Returns the plaintext once."""
    from internal.mcp.grants import issue_grant

    live = await db.scalar(
        select(func.count())
        .select_from(McpPersonalToken)
        .join(OAuthGrant, OAuthGrant.id == McpPersonalToken.grant_id)
        .where(
            OAuthGrant.user_id == user_id,
            OAuthGrant.revoked_at.is_(None),
            # Expired tokens are already refused — they must not eat the cap.
            (McpPersonalToken.expires_at.is_(None))
            | (McpPersonalToken.expires_at > datetime.now(UTC)),
        )
    )
    if (live or 0) >= MAX_LIVE_PATS_PER_USER:
        raise ValueError("personal token limit reached")

    token_id = uuid.uuid4()
    grant = await issue_grant(
        db,
        user_id=user_id,
        company_id=company_id,
        client_id=f"{PAT_CLIENT_ID_PREFIX}{token_id}",
        client_name=name,
        scopes=scopes,
    )
    token = _generate_token()
    row = McpPersonalToken(
        id=token_id,
        grant_id=grant.id,
        token_hash=hash_refresh_token(token),
        token_prefix=token[:_TOKEN_PREFIX_LEN],
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    return grant, row, token


async def resolve_pat(db: AsyncSession, token: str) -> McpPersonalToken | None:
    """Live PAT row for a bearer, or None for unknown/expired."""
    row = await db.scalar(
        select(McpPersonalToken).where(McpPersonalToken.token_hash == hash_refresh_token(token))
    )
    if row is None:
        return None
    if row.expires_at is not None and row.expires_at <= datetime.now(UTC):
        return None
    return row


async def list_pats(db: AsyncSession, user_id: uuid.UUID) -> dict[uuid.UUID, McpPersonalToken]:
    """{grant_id: row} for the user's live PATs — merged into connected-apps."""
    rows = await db.scalars(
        select(McpPersonalToken)
        .join(OAuthGrant, OAuthGrant.id == McpPersonalToken.grant_id)
        .where(OAuthGrant.user_id == user_id, OAuthGrant.revoked_at.is_(None))
    )
    return {row.grant_id: row for row in rows}
