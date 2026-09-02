"""Smoke coverage for social-account Pydantic shapes (ADR 0022)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from schemas.social import SocialAccountItem, SocialAccountUpsert


def test_upsert_strips_and_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        SocialAccountUpsert(ig_user_id="  ", access_token="long-enough-token")
    with pytest.raises(ValidationError):
        SocialAccountUpsert(ig_user_id="1784", access_token="short")
    body = SocialAccountUpsert(
        ig_user_id="  17841400  ",
        access_token="  IGQW-long-token  ",
    )
    assert body.ig_user_id == "17841400"
    assert body.access_token == "IGQW-long-token"


def test_item_never_requires_raw_token() -> None:
    now = datetime.now(UTC)
    item = SocialAccountItem(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        platform="instagram",
        ig_user_id="17841400",
        token_last4="oken",
        expires_at=None,
        last_verified_at=None,
        last_error_kind=None,
        created_at=now,
        updated_at=now,
    )
    dumped = item.model_dump()
    assert "access_token" not in dumped
    assert dumped["token_last4"] == "oken"
