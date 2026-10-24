"""MCP access tokens (ADR 0051 §4).

Claims ride on the codebase's ``type`` convention so ``decode_token``
enforces isolation both ways: a web ``access`` token is refused at
``/api/mcp`` and an ``mcp_access`` token is refused by every other ``/api``
route. ``aud`` binds the token to this install's MCP endpoint (RFC 8707).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import jwt

from internal.auth.jwt import ALGORITHM
from internal.config import settings

if TYPE_CHECKING:
    from internal.memory.models import OAuthGrant

TOKEN_TYPE_MCP_ACCESS = "mcp_access"
MCP_PATH = "/api/mcp"


@dataclass(frozen=True)
class McpAccessClaims:
    """Verified MCP token content — the only identity the adapter trusts."""

    user_id: uuid.UUID
    company_id: uuid.UUID
    grant_id: uuid.UUID
    scopes: list[str]


@dataclass
class McpTokenError(Exception):
    """Bearer-token refusal; ``reason`` picks the 401 challenge detail."""

    reason: str

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def mcp_resource_url() -> str:
    """This install's MCP endpoint — the ``aud``/``resource`` value."""
    from internal.instance.config import get_snapshot

    return f"{get_snapshot().web_base_url}{MCP_PATH}"


def create_mcp_access_token(
    grant: OAuthGrant, *, resource: str | None = None
) -> tuple[str, datetime]:
    """Mint a short-lived JWT bound to the grant's user, company and scopes."""
    expires = datetime.now(UTC) + timedelta(minutes=settings.mcp_access_expire_minutes)
    payload = {
        "sub": str(grant.user_id),
        "type": TOKEN_TYPE_MCP_ACCESS,
        "aud": resource or mcp_resource_url(),
        "cid": str(grant.company_id),
        "gid": str(grant.id),
        "scope": " ".join(grant.scopes or []),
        "iat": datetime.now(UTC),
        "exp": expires,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM), expires


def verify_mcp_access_token(token: str, *, resource: str | None = None) -> McpAccessClaims:
    """Verify signature, type, audience and required claims; never touches DB."""
    expected_aud = resource or mcp_resource_url()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[ALGORITHM], options={"verify_aud": False}
        )
    except jwt.ExpiredSignatureError as exc:
        raise McpTokenError("expired") from exc
    except jwt.InvalidTokenError as exc:
        raise McpTokenError("invalid") from exc

    if payload.get("type") != TOKEN_TYPE_MCP_ACCESS:
        raise McpTokenError("invalid")
    if payload.get("aud") != expected_aud:
        raise McpTokenError("invalid_audience")
    try:
        claims = McpAccessClaims(
            user_id=uuid.UUID(str(payload["sub"])),
            company_id=uuid.UUID(str(payload["cid"])),
            grant_id=uuid.UUID(str(payload["gid"])),
            scopes=[s for s in str(payload["scope"]).split() if s],
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise McpTokenError("invalid") from exc
    return claims
