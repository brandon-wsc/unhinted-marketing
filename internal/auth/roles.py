"""Platform privilege levels (ADR 0005).

Numeric ladder 0–10 on ``users.platform_level`` with named rungs and gaps so
future tiers slot in without renumbering. Threshold checks: a user passes when
``user.platform_level >= required``. Tenant RBAC (``organization_members.role``)
is a separate, per-company concern.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import IntEnum
from typing import Annotated

from fastapi import Depends, HTTPException, status

from internal.auth.deps import get_current_user
from internal.memory.models import User


class PlatformLevel(IntEnum):
    GUEST = 0  # reserved — unverified / restricted
    TRIAL = 1  # reserved — trial accounts
    MEMBER = 3  # default registered user
    MEMBER_PLUS = 4  # reserved — paid / advanced features
    SUPPORT = 5  # reserved — internal CS assist; no LLM internals
    ADMIN = 6  # read-only LLM call records / traces
    OPS_ADMIN = 7  # reserved — content ops (signals / questions)
    SECURITY_ADMIN = 8  # reserved — user / audit management
    SUPERADMIN = 9  # full — incl. granting/revoking admin
    OWNER = 10  # reserved — system / root


def parse_platform_level(raw: str) -> PlatformLevel:
    """Accept a rung name (``superadmin``) or a number in the ladder (``9``)."""
    text = raw.strip()
    try:
        return PlatformLevel[text.upper()]
    except KeyError:
        pass
    try:
        return PlatformLevel(int(text))
    except (ValueError, KeyError):
        valid = ", ".join(f"{lvl.name.lower()}={int(lvl)}" for lvl in PlatformLevel)
        raise ValueError(f"Unknown platform level {raw!r} — use one of: {valid}") from None


def require_platform_level(
    minimum: PlatformLevel,
) -> Callable[[Annotated[User, Depends(get_current_user)]], Awaitable[User]]:
    """FastAPI dependency factory: 403 unless the user meets the minimum level."""

    async def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.platform_level < minimum:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient platform level",
            )
        return user

    return dependency
