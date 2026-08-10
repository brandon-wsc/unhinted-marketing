"""Company settings routes — voice knobs + exemplar promote (knowledge K1/K5)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.auth.org import (
    COMPANY_SETTINGS_EDITOR_ROLES,
    require_company_access,
    require_company_settings_editor,
)
from internal.memory.database import get_db
from internal.memory.models import User
from internal.memory.repos import get_company, get_org_membership, update_company_profile
from internal.session.voice import (
    normalize_exemplar_captions,
    normalize_roast_level,
    prepend_exemplar_caption,
    roast_level_from_profile,
)
from schemas.company import (
    CompanyVoiceSettings,
    CompanyVoiceUpdate,
    ExemplarPromoteRequest,
    ExemplarPromoteResponse,
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
