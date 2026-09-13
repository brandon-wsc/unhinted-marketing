"""Org invite token helpers."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from internal.auth.jwt import hash_refresh_token

INVITE_TTL_DAYS = 7


def normalize_invite_email(email: str) -> str:
    return email.strip().lower()


def generate_invite_token() -> str:
    return secrets.token_urlsafe(48)


def hash_invite_token(token: str) -> str:
    return hash_refresh_token(token)


def invite_expires_at(*, now: datetime | None = None) -> datetime:
    base = now or datetime.now(UTC)
    return base + timedelta(days=INVITE_TTL_DAYS)


def build_invite_url(raw_token: str) -> str:
    from internal.instance.config import get_snapshot

    base = get_snapshot().web_base_url.rstrip("/")
    return f"{base}/invite/{raw_token}"
