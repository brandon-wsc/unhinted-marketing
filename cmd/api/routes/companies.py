"""Company settings routes — voice knobs + exemplar promote (knowledge K1/K5)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.auth.invites import (
    build_invite_url,
    generate_invite_token,
    hash_invite_token,
    invite_expires_at,
    normalize_invite_email,
)
from internal.auth.org import (
    COMPANY_SETTINGS_EDITOR_ROLES,
    MANAGEABLE_MEMBER_ROLES,
    require_company_access,
    require_company_settings_editor,
)
from internal.auth.rate_limit import enforce_invite_rate_limit
from internal.memory.database import get_db
from internal.memory.models import OrganizationMember, OrgInvite, User
from internal.memory.repos import (
    create_org_invite,
    delete_org_member,
    get_company,
    get_org_invite,
    get_org_member_by_email,
    get_org_membership,
    list_org_members,
    list_pending_org_invites,
    revoke_org_invite,
    update_company_name,
    update_company_profile,
    update_org_member_role,
    user_has_org_access,
)
from internal.notify import send_invite_email
from internal.session.voice import (
    normalize_exemplar_captions,
    normalize_roast_level,
    prepend_exemplar_caption,
    roast_level_from_profile,
)
from schemas.company import (
    CompanyMember,
    CompanyMemberListResponse,
    CompanyMemberRoleUpdate,
    CompanySummary,
    CompanyUpdate,
    CompanyVoiceSettings,
    CompanyVoiceUpdate,
    ExemplarPromoteRequest,
    ExemplarPromoteResponse,
    OrgInviteCreate,
    OrgInviteItem,
    OrgInviteListResponse,
)

router = APIRouter(prefix="/companies", tags=["companies"])


def _phrases_from_profile(profile: dict[str, Any]) -> list[str]:
    raw = profile.get("forbidden_phrases")
    if isinstance(raw, list):
        return [str(p).strip() for p in raw if str(p).strip()][:15]
    if isinstance(raw, str) and raw.strip():
        return [p.strip() for p in raw.split(",") if p.strip()][:15]
    return []


def _voice_from_company(
    company_id: uuid.UUID,
    profile: dict[str, Any] | None,
    *,
    can_edit: bool,
) -> CompanyVoiceSettings:
    profile = dict(profile or {})
    locale = str(profile.get("locale") or "zh-HK").strip() or "zh-HK"
    notes = profile.get("tone_notes")
    return CompanyVoiceSettings(
        company_id=company_id,
        roast_level=roast_level_from_profile(profile),
        locale=locale,
        forbidden_phrases=_phrases_from_profile(profile),
        tone_notes=str(notes).strip() if notes not in (None, "") else "",
        exemplar_captions=normalize_exemplar_captions(profile.get("exemplar_captions")),
        can_edit=can_edit,
    )


def _member_item(membership: OrganizationMember, user: User) -> CompanyMember:
    return CompanyMember(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=membership.role,
        joined_at=membership.created_at,
    )


@router.patch("/{company_id}", response_model=CompanySummary)
async def patch_company(
    body: CompanyUpdate,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanySummary:
    company = await get_company(db, company_id)
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    await update_company_name(db, company, body.name)
    await db.commit()
    await db.refresh(company)
    return CompanySummary(id=company.id, name=company.name, slug=company.slug)


@router.get("/{company_id}/members", response_model=CompanyMemberListResponse)
async def list_company_members(
    company_id: Annotated[uuid.UUID, Depends(require_company_access)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyMemberListResponse:
    rows = await list_org_members(db, company_id)
    return CompanyMemberListResponse(
        company_id=company_id,
        items=[_member_item(m, u) for m, u in rows],
    )


@router.patch("/{company_id}/members/{user_id}", response_model=CompanyMember)
async def patch_company_member_role(
    body: CompanyMemberRoleUpdate,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyMember:
    target = await get_org_membership(db, user_id, company_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if target.role == "owner":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot change the owner's role",
        )
    if body.role not in MANAGEABLE_MEMBER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Role must be admin or member",
        )

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    await update_org_member_role(db, target, body.role)
    await db.commit()
    await db.refresh(target)
    return _member_item(target, user)


@router.delete("/{company_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_company_member(
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    actor: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    if not await user_has_org_access(db, actor.id, company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    target = await get_org_membership(db, user_id, company_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    is_self = actor.id == user_id
    if is_self:
        if target.role == "owner":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The company owner cannot leave until ownership is transferred",
            )
    else:
        actor_membership = await get_org_membership(db, actor.id, company_id)
        if not actor_membership or actor_membership.role not in COMPANY_SETTINGS_EDITOR_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        if target.role == "owner":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot remove the company owner",
            )

    await delete_org_member(db, target)
    await db.commit(    )


def _invite_item(invite: OrgInvite, *, invite_url: str | None = None) -> OrgInviteItem:
    return OrgInviteItem(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        invite_url=invite_url,
        expires_at=invite.expires_at,
        accepted_at=invite.accepted_at,
        revoked_at=invite.revoked_at,
        created_at=invite.created_at,
    )


@router.post("/{company_id}/invites", response_model=OrgInviteItem, status_code=status.HTTP_201_CREATED)
async def create_company_invite(
    body: OrgInviteCreate,
    background_tasks: BackgroundTasks,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrgInviteItem:
    enforce_invite_rate_limit(user_id=user.id)
    company = await get_company(db, company_id)
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    email = normalize_invite_email(str(body.email))
    if await get_org_member_by_email(db, company_id, email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email already belongs to a member of this company",
        )
    raw_token = generate_invite_token()
    invite_url = build_invite_url(raw_token)
    try:
        invite = await create_org_invite(
            db,
            organization_id=company_id,
            email=email,
            role=body.role,
            token_hash=hash_invite_token(raw_token),
            invited_by=user.id,
            expires_at=invite_expires_at(),
        )
        await db.commit()
        await db.refresh(invite)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending invite already exists for this email",
        ) from None

    background_tasks.add_task(
        send_invite_email,
        to_email=email,
        invite_url=invite_url,
        organization_name=company.name,
    )
    return _invite_item(invite, invite_url=invite_url)


@router.get("/{company_id}/invites", response_model=OrgInviteListResponse)
async def list_company_invites(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrgInviteListResponse:
    invites = await list_pending_org_invites(db, company_id)
    return OrgInviteListResponse(
        company_id=company_id,
        items=[_invite_item(invite) for invite in invites],
    )


@router.delete("/{company_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_company_invite(
    invite_id: uuid.UUID,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    invite = await get_org_invite(db, company_id, invite_id)
    if not invite or invite.accepted_at or invite.revoked_at:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    await revoke_org_invite(db, invite)
    await db.commit()


@router.get("/{company_id}/voice", response_model=CompanyVoiceSettings)
async def get_company_voice(
    company_id: Annotated[uuid.UUID, Depends(require_company_access)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyVoiceSettings:
    company = await get_company(db, company_id)
    assert company is not None  # require_company_access already checked
    membership = await get_org_membership(db, user.id, company_id)
    can_edit = bool(membership and membership.role in COMPANY_SETTINGS_EDITOR_ROLES)
    return _voice_from_company(company_id, company.profile, can_edit=can_edit)


@router.patch("/{company_id}/voice", response_model=CompanyVoiceSettings)
async def patch_company_voice(
    body: CompanyVoiceUpdate,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyVoiceSettings:
    company = await get_company(db, company_id)
    assert company is not None
    await update_company_profile(
        db,
        company,
        patch={
            "roast_level": normalize_roast_level(body.roast_level),
            "locale": body.locale,
            "forbidden_phrases": body.forbidden_phrases,
            "tone_notes": body.tone_notes,
            "exemplar_captions": body.exemplar_captions,
        },
    )
    await db.commit()
    await db.refresh(company)
    return _voice_from_company(company_id, company.profile, can_edit=True)


@router.post(
    "/{company_id}/voice/exemplars",
    response_model=ExemplarPromoteResponse,
)
async def promote_voice_exemplar(
    body: ExemplarPromoteRequest,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ExemplarPromoteResponse:
    """Manual promote from Confirm / draft — not chat auto-write (COLLECT K5)."""
    company = await get_company(db, company_id)
    assert company is not None
    profile = dict(company.profile or {})
    before = normalize_exemplar_captions(profile.get("exemplar_captions"))
    after = prepend_exemplar_caption(before, body.caption)
    await update_company_profile(
        db,
        company,
        patch={"exemplar_captions": after},
    )
    await db.commit()
    return ExemplarPromoteResponse(
        company_id=company_id,
        exemplar_captions=after,
        added=after != before,
    )
