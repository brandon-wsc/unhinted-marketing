"""Platform privilege ladder + gate (ADR 0005)."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from internal.auth.roles import PlatformLevel, parse_platform_level, require_platform_level


def test_ladder_values_and_gaps() -> None:
    assert PlatformLevel.GUEST == 0
    assert PlatformLevel.MEMBER == 3
    assert PlatformLevel.ADMIN == 6
    assert PlatformLevel.SUPERADMIN == 9
    assert PlatformLevel.OWNER == 10
    # 2 stays unnamed on purpose — room for a future rung between TRIAL and MEMBER.
    unnamed = set(range(0, 11)) - {int(lvl) for lvl in PlatformLevel}
    assert unnamed == {2}


def test_parse_by_name_and_number() -> None:
    assert parse_platform_level("superadmin") is PlatformLevel.SUPERADMIN
    assert parse_platform_level(" Admin ") is PlatformLevel.ADMIN
    assert parse_platform_level("9") is PlatformLevel.SUPERADMIN
    assert parse_platform_level("3") is PlatformLevel.MEMBER


def test_parse_rejects_unknown_and_gaps() -> None:
    with pytest.raises(ValueError, match="Unknown platform level"):
        parse_platform_level("root")
    with pytest.raises(ValueError, match="Unknown platform level"):
        parse_platform_level("2")


async def test_require_platform_level_allows_at_or_above() -> None:
    dep = require_platform_level(PlatformLevel.ADMIN)
    superadmin = SimpleNamespace(platform_level=int(PlatformLevel.SUPERADMIN))
    assert await dep(superadmin) is superadmin
    admin = SimpleNamespace(platform_level=int(PlatformLevel.ADMIN))
    assert await dep(admin) is admin


async def test_require_platform_level_forbids_below() -> None:
    dep = require_platform_level(PlatformLevel.ADMIN)
    member = SimpleNamespace(platform_level=int(PlatformLevel.MEMBER))
    with pytest.raises(HTTPException) as exc_info:
        await dep(member)
    assert exc_info.value.status_code == 403
