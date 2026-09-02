"""Org Instagram credentials for Confirm publish (ADR 0022). Editor-only; no raw tokens."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.auth.org import require_company_settings_editor
from internal.llm.keys import ByokEncryptionError, encrypt_key, mask_key
from internal.memory.database import get_db
from internal.memory.models import SocialAccount, User
from internal.memory.repos import (
    delete_social_account,
    list_social_accounts,
    upsert_social_account,
)
from schemas.social import SocialAccountItem, SocialAccountList, SocialAccountUpsert

router = APIRouter(prefix="/companies/{company_id}/social-accounts", tags=["social"])

_PLATFORMS = frozenset({"instagram"})


def _encrypt_or_503(raw: str) -> str:
    try:
        return encrypt_key(raw)
    except ByokEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _require_platform(platform: str) -> str:
    if platform not in _PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown social platform",
        )
    return platform


def _item(row: SocialAccount) -> SocialAccountItem:
    return SocialAccountItem.model_validate(row)


@router.get("", response_model=SocialAccountList)
async def list_accounts(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SocialAccountList:
    rows = await list_social_accounts(db, company_id)
    return SocialAccountList(items=[_item(row) for row in rows])


@router.put("/{platform}", response_model=SocialAccountItem)
async def upsert_account(
    platform: str,
    body: SocialAccountUpsert,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SocialAccountItem:
    _require_platform(platform)
    row = await upsert_social_account(
        db,
        company_id=company_id,
        platform=platform,
        ig_user_id=body.ig_user_id,
        access_token_encrypted=_encrypt_or_503(body.access_token),
        token_last4=mask_key(body.access_token),
        expires_at=_aware(body.expires_at),
        created_by=user.id,
    )
    await db.commit()
    await db.refresh(row)
    return _item(row)


@router.delete("/{platform}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_account(
    platform: str,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    _require_platform(platform)
    deleted = await delete_social_account(db, company_id, platform)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="social_account_not_connected",
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
