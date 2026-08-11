"""Shared helpers for API integration tests."""

from __future__ import annotations

import uuid

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
) -> dict:
    """Register and return token response JSON (sets refresh cookie on client)."""
    payload = {
        "email": email or f"user-{uuid.uuid4().hex[:10]}@example.com",
        "password": password,
        "display_name": display_name,
        "organization_name": organization_name,
    }
    res = await client.post("/api/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


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


async def seed_preview_session(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    approval_token: str = "test-approval-token-001",
    revision: int = 1,
) -> uuid.UUID:
    """Insert a PREVIEW-mode session + draft without LangGraph."""
    session = Session(
        user_id=user_id,
        company_id=company_id,
        mode=MODE_PREVIEW,
        status="active",
        state={
            "revision": revision,
            "approval_token": approval_token,
            "draft": {"caption": "seed", "hashtags": [], "cta": ""},
            "image_url": "placeholder://seed",
        },
    )
    db_session.add(session)
    await db_session.flush()
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
    await repos.upsert_preview_draft(
        db_session,
        session_id=session.id,
        revision=revision,
        copy={"caption": "seed", "hashtags": [], "cta": ""},
        image_url="placeholder://seed",
        image_plan={"prompt": "seed plan", "format": "single"},
        media_ids=[image.id],
        source_signal_ids=[],
        approval_token=approval_token,
        platform="instagram",
    )
    await db_session.commit()
    return session.id
