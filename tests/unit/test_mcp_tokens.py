"""MCP access tokens (internal/mcp/tokens.py) — ADR 0051 §4, no Postgres.

Claims use the codebase's ``type`` convention so ``decode_token`` enforces
isolation both ways: a web ``access`` token is refused at ``/api/mcp`` and an
``mcp_access`` token is refused by every other ``/api`` route.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest

from internal.auth.jwt import ALGORITHM, TOKEN_TYPE_ACCESS, create_access_token, decode_token
from internal.config import settings
from internal.mcp.tokens import (
    McpTokenError,
    create_mcp_access_token,
    verify_mcp_access_token,
)

RESOURCE = "https://app.example/api/mcp"
OTHER_RESOURCE = "https://other.example/api/mcp"

USER = uuid.uuid4()
COMPANY = uuid.uuid4()
GRANT = uuid.uuid4()


def _grant(scopes=("knowledge:read", "drafts:write")):
    return SimpleNamespace(id=GRANT, user_id=USER, company_id=COMPANY, scopes=list(scopes))


def test_mint_and_verify_round_trip():
    token, _expires = create_mcp_access_token(_grant(), resource=RESOURCE)
    claims = verify_mcp_access_token(token, resource=RESOURCE)
    assert claims.user_id == USER
    assert claims.company_id == COMPANY
    assert claims.grant_id == GRANT
    assert claims.scopes == ["knowledge:read", "drafts:write"]


def test_rejects_token_minted_for_another_resource():
    token, _ = create_mcp_access_token(_grant(), resource=OTHER_RESOURCE)
    with pytest.raises(McpTokenError) as exc:
        verify_mcp_access_token(token, resource=RESOURCE)
    assert exc.value.reason == "invalid_audience"


def test_web_access_token_is_not_an_mcp_token():
    web_token, _ = create_access_token(USER)
    with pytest.raises(McpTokenError):
        verify_mcp_access_token(web_token, resource=RESOURCE)


def test_mcp_token_is_not_a_web_token():
    token, _ = create_mcp_access_token(_grant(), resource=RESOURCE)
    with pytest.raises(ValueError):
        decode_token(token, TOKEN_TYPE_ACCESS)


def test_expired_token_is_refused():
    expired = jwt.encode(
        {
            "sub": str(USER),
            "type": "mcp_access",
            "aud": RESOURCE,
            "cid": str(COMPANY),
            "gid": str(GRANT),
            "scope": "drafts:write",
            "iat": datetime.now(UTC) - timedelta(hours=1),
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )
    with pytest.raises(McpTokenError) as exc:
        verify_mcp_access_token(expired, resource=RESOURCE)
    assert exc.value.reason == "expired"


def test_garbage_is_refused():
    with pytest.raises(McpTokenError) as exc:
        verify_mcp_access_token("not-a-jwt", resource=RESOURCE)
    assert exc.value.reason == "invalid"


def test_missing_required_claim_is_refused():
    token = jwt.encode(
        {
            "sub": str(USER),
            "type": "mcp_access",
            "aud": RESOURCE,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )
    with pytest.raises(McpTokenError):
        verify_mcp_access_token(token, resource=RESOURCE)
