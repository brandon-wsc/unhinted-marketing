"""Shared helpers for API integration tests."""

from __future__ import annotations

import uuid
from datetime import datetime

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory import repos
from internal.memory.models import OrganizationMember, Session
from internal.session.state import MODE_PREVIEW


def auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def register_user(
    client: AsyncClient,
    *,
    email: str | None = None,
    password: str = "password123",
    display_name: str = "Test User",
    organization_name: str = "Test Co",
    platform_level: int | None = None,
) -> dict:
    """Create a user via the service layer and mirror the TokenResponse shape.

    HTTP register is invite-only on on-prem after setup (ADR 0026), so the bulk
    of the suite seeds users directly. The refresh cookie is set on the client
    the same way the route would (Path=/api/auth).
    """
    from internal.auth.service import (
        get_user_with_memberships,
    )
    from internal.auth.service import (
        register_user as svc_register_user,
    )
    from internal.config import settings
    from internal.memory.database import open_session

    async with open_session() as db:
        user, access, refresh = await svc_register_user(
            db,
            email=email or f"user-{uuid.uuid4().hex[:10]}@example.com",
            password=password,
            display_name=display_name,
            organization_name=organization_name,
            platform_level=platform_level,
        )
        user = await get_user_with_memberships(db, user.id)
        assert user is not None
        orgs = [
            {
                "id": str(m.organization.id),
                "name": m.organization.name,
                "slug": m.organization.slug,
                "role": m.role,
            }
            for m in user.memberships
        ]
        body = {
            "access_token": access,
            "token_type": "bearer",
            "expires_in": settings.jwt_access_expire_minutes * 60,
            "user": {
                "id": str(user.id),
                "email": user.email,
                "display_name": user.display_name,
                "is_active": user.is_active,
                "platform_level": user.platform_level,
                "created_at": user.created_at.isoformat(),
                "organizations": orgs,
            },
        }
    client.cookies.delete("refresh_token", path="/api/auth")
    client.cookies.set("refresh_token", refresh, path="/api/auth")
    return body


async def join_org(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    role: str = "member",
) -> OrganizationMember:
    """Move a registered user into a company (MVP one-org: drops their default org membership)."""
    existing = await db_session.scalar(
        select(OrganizationMember).where(OrganizationMember.user_id == user_id)
    )
    if existing:
        await db_session.delete(existing)
    membership = OrganizationMember(
        user_id=user_id,
        organization_id=company_id,
        role=role,
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(membership)
    return membership


async def strip_org_membership(
    db_session: AsyncSession,
    user_id: uuid.UUID,
) -> None:
    """Remove a user's org membership (tests: invite accept without a current org)."""
    membership = await db_session.scalar(
        select(OrganizationMember).where(OrganizationMember.user_id == user_id)
    )
    if membership:
        await db_session.delete(membership)
        await db_session.commit()


def invite_token_from_url(invite_url: str) -> str:
    """Extract raw token from `{base}/invite/{token}` invite links."""
    marker = "/invite/"
    if marker not in invite_url:
        raise ValueError(f"unexpected invite_url shape: {invite_url}")
    return invite_url.split(marker, 1)[1].split("?", 1)[0].strip()


async def seed_preview_session(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    approval_token: str = "test-approval-token-001",
    revision: int = 1,
    draft_created_at: datetime | None = None,
    with_media: bool = True,
) -> uuid.UUID:
    """Insert a PREVIEW-mode session + draft without LangGraph."""
    image_url = "placeholder://seed" if with_media else None
    session = Session(
        user_id=user_id,
        company_id=company_id,
        mode=MODE_PREVIEW,
        status="active",
        state={
            "revision": revision,
            "approval_token": approval_token,
            "draft": {"caption": "seed", "hashtags": [], "cta": ""},
            "image_url": image_url,
        },
    )
    db_session.add(session)
    await db_session.flush()
    media_ids: list[uuid.UUID] = []
    image_plan = {"prompt": "seed plan", "format": "single"} if with_media else None
    if with_media:
        image = await repos.insert_preview_image(
            db_session,
            session_id=session.id,
            url="placeholder://seed",
            plan={"prompt": "seed plan", "format": "single"},
            format="single",
            role="primary",
            seq=0,
            status="ready",
        )
        media_ids = [image.id]
    await repos.upsert_preview_draft(
        db_session,
        session_id=session.id,
        revision=revision,
        copy={"caption": "seed", "hashtags": [], "cta": ""},
        image_url=image_url,
        image_plan=image_plan,
        media_ids=media_ids,
        source_signal_ids=[],
        approval_token=approval_token,
        platform="instagram",
        created_at=draft_created_at,
    )
    await db_session.commit()
    return session.id
