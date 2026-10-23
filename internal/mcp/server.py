"""JSON-RPC dispatch for ``POST /api/mcp`` (ADR 0051, spec 2026-07-28).

Stateless core: every POST is one self-describing JSON-RPC request; replies
are ``application/json`` (the request-scoped SSE alternative is left to the
SDK upgrade). ``tools/list`` is unscoped; ``tools/call`` checks the grant's
scopes first — a missing scope answers HTTP 403 with a step-up challenge.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from internal.session.guards import SessionGuardError
from schemas.mcp import (
    MCP_TOOL_SCOPES,
    ChooseAngleArgs,
    RevisePostDraftArgs,
    SessionToolArgs,
    StartPostDraftArgs,
)

from . import tools
from .auth import McpContext, insufficient_scope
from .errors import ToolRefusal, refusal_reason

RPC_PARSE_ERROR = -32700
RPC_INVALID_REQUEST = -32600
RPC_METHOD_NOT_FOUND = -32601
RPC_INVALID_PARAMS = -32602
RPC_INTERNAL_ERROR = -32603

# Spec version we answer `initialize` with; clients advertise theirs in params.
PROTOCOL_VERSION = "2026-07-28"
# Versions whose Streamable HTTP + tools/structuredContent shape this surface
# satisfies. Anything else (e.g. 2025-03-26, no structuredContent) gets ours.
SUPPORTED_PROTOCOL_VERSIONS = frozenset({PROTOCOL_VERSION, "2025-11-25", "2025-06-18"})

# §13 — per-grant rate limit on mutating tools, sliding 60s window. The
# concurrent-draft cap lives next to the turn tracking in tools.py.
MUTATING_TOOLS = frozenset(
    {"start_post_draft", "choose_angle", "approve_image", "revise_post_draft", "cancel_post_draft"}
)
RATE_LIMIT_MUTATING = 30
_rate_windows: dict[uuid.UUID, deque[float]] = {}


def _check_grant_rate(ctx: McpContext, name: str) -> None:
    if str(name) not in MUTATING_TOOLS:
        return
    now = time.monotonic()
    win = _rate_windows.setdefault(ctx.claims.grant_id, deque())
    while win and now - win[0] > 60.0:
        win.popleft()
    if len(win) >= RATE_LIMIT_MUTATING:
        raise ToolRefusal("rate_limited", "Rate limit reached — slow down and retry shortly")
    win.append(now)


class _Tool(BaseModel):
    handler: Callable[..., Awaitable[dict]]
    args_model: type[BaseModel] | None
    description: str


TOOLS: dict[str, _Tool] = {
    "get_brand_context": _Tool(
        handler=tools.get_brand_context,
        args_model=None,
        description=(
            "Read-only brand digest for the granted company: voice pack "
            "(tone, roast_level), product names and one-line summaries."
        ),
    ),
    "start_post_draft": _Tool(
        handler=tools.start_post_draft,
        args_model=StartPostDraftArgs,
        description=(
            "Start a post draft from a brief plus optional pasted context. "
            "Returns session_id + status=running; poll get_post_draft. With "
            "auto=true the server answers each review gate with its "
            "recommendation — the image gate additionally needs the "
            "images:generate scope. Publishing always stays a UI Confirm."
        ),
    ),
    "get_post_draft": _Tool(
        handler=tools.get_post_draft,
        args_model=SessionToolArgs,
        description=(
            "Current draft state: running | awaiting_angle_pick | "
            "awaiting_image_ok | awaiting_reply | ready | failed | "
            "cancelled. awaiting_reply carries the assistant's message — "
            "answer it with revise_post_draft. When ready it carries the "
            "preview and a confirm_url for the user to publish in the "
            "Unhinted UI."
        ),
    ),
    "choose_angle": _Tool(
        handler=tools.choose_angle,
        args_model=ChooseAngleArgs,
        description=(
            "Answer the angle/persona/format gate. Show the offered angles "
            "to the user unless they delegated the choice. Pass feedback "
            "instead of a pick to ask for fresh angles."
        ),
    ),
    "approve_image": _Tool(
        handler=tools.approve_image,
        args_model=SessionToolArgs,
        description=(
            "Approve the parked image plan and generate the image. Spends "
            "the member's token quota — ask the user first. Requires the "
            "images:generate scope."
        ),
    ),
    "revise_post_draft": _Tool(
        handler=tools.revise_post_draft,
        args_model=RevisePostDraftArgs,
        description=(
            "Send a revision instruction to the draft. While image-parked "
            "a direction change writes a new script + plan (ADR 0036)."
        ),
    ),
    "cancel_post_draft": _Tool(
        handler=tools.cancel_post_draft,
        args_model=SessionToolArgs,
        description="Stop the draft: cancels an in-flight turn or discards a parked one.",
    ),
}


def _rpc_error(rpc_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def _rpc_result(rpc_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _tool_error_result(rpc_id: Any, reason: str, message: str, session_id: Any = None) -> dict:
    """A refusal is a tool result, not an RPC error (tools/call contract)."""
    structured: dict[str, Any] = {"reason": reason, "error": message}
    if session_id is not None:
        structured["session_id"] = str(session_id)
    return _rpc_result(
        rpc_id,
        {
            "isError": True,
            "content": [{"type": "text", "text": message}],
            "structuredContent": structured,
        },
    )


def _tool_result(rpc_id: Any, data: dict[str, Any]) -> dict:
    clean = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in data.items()}
    return _rpc_result(
        rpc_id,
        {
            "isError": False,
            "content": [
                {"type": "text", "text": json.dumps(clean, default=str, ensure_ascii=False)}
            ],
            "structuredContent": clean,
        },
    )


def _tools_list() -> dict:
    return {
        "tools": [
            {
                "name": name,
                "description": tool.description,
                "inputSchema": (
                    tool.args_model.model_json_schema()
                    if tool.args_model is not None
                    else {"type": "object", "properties": {}}
                ),
            }
            for name, tool in TOOLS.items()
        ]
    }


def _initialize_result(params: dict[str, Any]) -> dict:
    from cmd.api.routes.meta import API_VERSION

    return {
        # Keep the client's version only when we support it; otherwise offer ours.
        "protocolVersion": requested
        if (requested := params.get("protocolVersion")) in SUPPORTED_PROTOCOL_VERSIONS
        else PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "unhinted-marketing", "version": API_VERSION},
    }


async def dispatch(ctx: McpContext, body: Any) -> dict | list | None:
    """Requests → responses. ``None`` means notifications only → HTTP 202.

    Batches are supported: each item gets its own response, notifications
    (no ``id``) are silently consumed as JSON-RPC requires.
    """
    if isinstance(body, list):
        if not body:
            return _rpc_error(None, RPC_INVALID_REQUEST, "Empty batch")
        responses = [resp for item in body if (resp := await _dispatch_one(ctx, item)) is not None]
        return responses or None
    return await _dispatch_one(ctx, body)


async def _dispatch_one(ctx: McpContext, body: Any) -> dict | None:
    """One JSON-RPC request → one response object, or None for a notification."""
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return _rpc_error(None, RPC_INVALID_REQUEST, "Expected a JSON-RPC 2.0 request")
    rpc_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if rpc_id is None:
        return None  # notification — never answered
    if method == "initialize":
        return _rpc_result(rpc_id, _initialize_result(params))
    if method == "ping":
        return _rpc_result(rpc_id, {})
    if method == "tools/list":
        return _rpc_result(rpc_id, _tools_list())
    if method != "tools/call":
        return _rpc_error(rpc_id, RPC_METHOD_NOT_FOUND, f"Unknown method: {method}")

    name = params.get("name")
    tool = TOOLS.get(str(name))
    if tool is None:
        return _rpc_error(rpc_id, RPC_INVALID_PARAMS, f"Unknown tool: {name}")

    required_scope = MCP_TOOL_SCOPES[str(name)]
    if required_scope not in ctx.scopes:
        raise insufficient_scope(required_scope)

    arguments = params.get("arguments") or {}
    if tool.args_model is not None:
        try:
            args = tool.args_model.model_validate(arguments)
        except ValidationError as exc:
            return _rpc_error(rpc_id, RPC_INVALID_PARAMS, f"Invalid arguments: {exc}")
    else:
        args = None

    try:
        _check_grant_rate(ctx, name)
        if args is None:
            data = await tool.handler(ctx)
        else:
            data = await tool.handler(ctx, args)
    except ToolRefusal as exc:
        return _tool_error_result(
            rpc_id, exc.reason, exc.message, params.get("arguments", {}).get("session_id")
        )
    except SessionGuardError as exc:
        return _tool_error_result(
            rpc_id,
            refusal_reason(exc),
            str(exc.detail),
            params.get("arguments", {}).get("session_id"),
        )
    return _tool_result(rpc_id, data)
