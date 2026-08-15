"""Public org invite preview + accept routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.auth.invites import hash_invite_token, normalize_invite_email
from internal.memory.database import get_db
from internal.memory.models import OrgInvite, User
from internal.memory.repos import (
    accept_org_invite,
    clear_bootstrap_solo_org,
    create_org_member,
    get_org_invite_by_token_hash,
)
from schemas.company import OrgInviteAcceptResponse, OrgInvitePreviewResponse

router = APIRouter(prefix="/invites", tags=["invites"])

_INVALID_INVITE = "Invalid or expired invite"


async def _pending_invite(db: AsyncSession, token: str) -> OrgInvite:
    invite = await get_org_invite_by_token_hash(db, hash_invite_token(token))
    if not invite or invite.revoked_at or invite.accepted_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_INVITE)
    if invite.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_INVITE)
    return invite


@router.get("/{token}", response_model=OrgInvitePreviewResponse)
async def preview_company_invite(
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrgInvitePreviewResponse:
    invite = await _pending_invite(db, token)
    return OrgInvitePreviewResponse(email=invite.email, company_name=invite.organization.name)


@router.post("/{token}/accept", response_model=OrgInviteAcceptResponse)
async def accept_company_invite(
    token: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrgInviteAcceptResponse:
    invite = await _pending_invite(db, token)
    if normalize_invite_email(user.email) != invite.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invite was sent to a different email address",
        )
    if not await clear_bootstrap_solo_org(db, user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already belong to an organization",
        )

    await accept_org_invite(db, invite)
    await create_org_member(
        db,
        user_id=user.id,
        company_id=invite.organization_id,
        role=invite.role,
    )
    await db.commit()
    return OrgInviteAcceptResponse(company_id=invite.organization_id, role=invite.role)
