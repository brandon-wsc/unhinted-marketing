"""Remote MCP endpoint (ADR 0051).

``POST /api/mcp`` — one stateless JSON-RPC request per POST (spec
2026-07-28). ``discovery_router`` serves the RFC 9728 protected-resource
metadata at the domain root — ADR 0006's only exception; ingress must route
``/.well-known/oauth-`` here instead of the SPA.
"""

from __future__ import annotations

import json
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from internal.instance.config import get_snapshot
from internal.mcp import server as mcp_server
from internal.mcp.auth import McpContext, get_mcp_context
from internal.mcp.grants import KNOWN_SCOPES
from internal.mcp.oauth import DEFAULT_SCOPES
from internal.mcp.tokens import MCP_PATH, mcp_resource_url
from internal.memory.database import get_db

router = APIRouter(tags=["mcp"])
discovery_router = APIRouter(tags=["oauth-discovery"])

_VALID_SCHEMES = {"http", "https"}


def _origin_allowed(request: Request) -> bool:
    """Streamable HTTP §Security: a foreign browser Origin is refused (403)."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    host = urlparse(get_snapshot().web_base_url).netloc
    return urlparse(origin).netloc == host


@router.post(MCP_PATH.removeprefix("/api"), status_code=200)
async def mcp_endpoint(
    request: Request,
    ctx: Annotated[McpContext, Depends(get_mcp_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    if not _origin_allowed(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Origin")
    try:
        body: Any = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": mcp_server.RPC_PARSE_ERROR, "message": "Invalid JSON"},
        }
    result = await mcp_server.dispatch(ctx, body)
    await db.commit()  # lands get_mcp_context's touch_grant (last_used_at)
    if result is None:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return result


@discovery_router.get("/.well-known/oauth-protected-resource/api/mcp")
async def protected_resource_metadata() -> dict[str, Any]:
    """RFC 9728 — how clients find this install's authorization server."""
    snap = get_snapshot()
    return {
        "resource": mcp_resource_url(),
        "authorization_servers": [snap.web_base_url],
        "scopes_supported": DEFAULT_SCOPES,
        "bearer_methods_supported": ["header"],
    }


@discovery_router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata() -> dict[str, Any]:
    """RFC 8414 — issuer = web_base_url; CIMD, no registration endpoint.

    MCP clients (Claude, Grok) select Client ID Metadata Documents only when
    this document advertises ``client_id_metadata_document_supported`` and
    public-client token auth. Missing the flag makes them fall through to
    Dynamic Client Registration, which this server does not offer (ADR 0053).
    """
    base = get_snapshot().web_base_url
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/api/oauth/authorize",
        "token_endpoint": f"{base}/api/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "client_id_metadata_document_supported": True,
        "scopes_supported": sorted(KNOWN_SCOPES),
    }
