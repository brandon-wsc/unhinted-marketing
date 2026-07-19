import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from internal.auth.jwt import (
    create_access_token,
    create_refresh_jwt,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from internal.config import settings
from internal.memory.models import Entity, OrganizationMember, RefreshToken, User

EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+\.)+[^@\s]+$")


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or "org"


async def register_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str,
    organization_name: str | None = None,
) -> tuple[User, str, str]:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("Invalid email address")
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters")

    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        raise AuthError("Email already registered", status_code=409)

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name.strip() or email.split("@")[0],
    )
    db.add(user)
    await db.flush()

    org_name = (organization_name or f"{user.display_name}'s Company").strip()
    base_slug = _slugify(org_name)
    slug = base_slug
    suffix = 1
    while await db.scalar(select(Entity.id).where(Entity.slug == slug)):
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    org = Entity(entity_type="company", slug=slug, name=org_name, profile={})
    db.add(org)
    await db.flush()

    membership = OrganizationMember(user_id=user.id, organization_id=org.id, role="owner")
    db.add(membership)

    access_token, _ = create_access_token(user.id)
    refresh_token, family_id = await _issue_refresh_token(db, user.id)
    await db.commit()
    await db.refresh(user)
    return user, access_token, refresh_token


async def login_user(
    db: AsyncSession, *, email: str, password: str
) -> tuple[User, str, str]:
    email = email.strip().lower()
    user = await db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password", status_code=401)
    if not user.is_active:
        raise AuthError("Account is disabled", status_code=403)

    access_token, _ = create_access_token(user.id)
    refresh_token, _ = await _issue_refresh_token(db, user.id)
    await db.commit()
    return user, access_token, refresh_token


async def refresh_session(
    db: AsyncSession, *, raw_refresh_token: str
) -> tuple[User, str, str]:
    token_hash = hash_refresh_token(raw_refresh_token)
    row = await db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .options(selectinload(RefreshToken.user))
    )
    if not row or row.revoked_at or row.expires_at < datetime.now(UTC):
        raise AuthError("Invalid refresh token", status_code=401)

    user = row.user
    if not user.is_active:
        raise AuthError("Account is disabled", status_code=403)

    row.revoked_at = datetime.now(UTC)
    access_token, _ = create_access_token(user.id)
    new_refresh, _ = await _issue_refresh_token(db, user.id, family_id=row.family_id)
    await db.commit()
    return user, access_token, new_refresh


async def logout_user(db: AsyncSession, *, raw_refresh_token: str) -> None:
    token_hash = hash_refresh_token(raw_refresh_token)
    row = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if row and not row.revoked_at:
        row.revoked_at = datetime.now(UTC)
        await db.commit()


async def get_user_with_memberships(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.scalar(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.memberships).selectinload(OrganizationMember.organization)
        )
    )


async def _issue_refresh_token(
    db: AsyncSession, user_id: uuid.UUID, family_id: uuid.UUID | None = None
) -> tuple[str, uuid.UUID]:
    family = family_id or uuid.uuid4()
    raw = generate_refresh_token()
    _, expires = create_refresh_jwt(user_id, family)
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(raw),
            family_id=family,
            expires_at=expires,
        )
    )
    return raw, family
