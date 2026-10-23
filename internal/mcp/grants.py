"""OAuth grants for external MCP clients (ADR 0051 §4).

A grant records one user consenting one client to one company with a scope
set. Access tokens carry only the grant id: membership, grant revocation and
``is_active`` are re-checked live on every request, so revoking a connected
app cuts the next call.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory.models import OAuthGrant

KNOWN_SCOPES = frozenset({"knowledge:read", "drafts:write", "images:generate"})


async def issue_grant(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    client_id: str,
    client_name: str,
    scopes: list[str],
) -> OAuthGrant:
    """Persist the consent; callers must commit."""
    unknown = set(scopes) - KNOWN_SCOPES
    if unknown:
        raise ValueError(f"unknown scopes: {sorted(unknown)}")
    grant = OAuthGrant(
        user_id=user_id,
        company_id=company_id,
        client_id=client_id.strip(),
        client_name=client_name.strip(),
        scopes=sorted(set(scopes)),
    )
    db.add(grant)
    await db.flush()
    return grant


async def get_active_grant(db: AsyncSession, grant_id: uuid.UUID) -> OAuthGrant | None:
    grant = await db.get(OAuthGrant, grant_id)
    if grant is None or grant.revoked_at is not None:
        return None
    return grant


async def list_connected_apps(db: AsyncSession, user_id: uuid.UUID) -> list[OAuthGrant]:
    """Non-revoked grants, newest first — the /account connected-apps list."""
    return list(
        await db.scalars(
            select(OAuthGrant)
            .where(OAuthGrant.user_id == user_id, OAuthGrant.revoked_at.is_(None))
            .order_by(OAuthGrant.created_at.desc())
        )
    )


async def revoke_grant(db: AsyncSession, *, user_id: uuid.UUID, grant_id: uuid.UUID) -> bool:
    """Revoke the grant if it belongs to ``user_id``; False when unknown."""
    grant = await get_active_grant(db, grant_id)
    if grant is None or grant.user_id != user_id:
        return False
    grant.revoked_at = datetime.now(UTC)
    return True


async def touch_grant(db: AsyncSession, grant: OAuthGrant) -> None:
    """Bump ``last_used_at`` on a successful authenticated call."""
    grant.last_used_at = datetime.now(UTC)
