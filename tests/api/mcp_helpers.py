"""Shared helpers for ADR 0051 remote MCP server tests.

Invented contract the implementation must satisfy (pinned by
tests/api/bdd/features/mcp.feature):

- ``POST /api/mcp`` — Streamable HTTP, spec ``2026-07-28`` stateless core:
  one JSON-RPC request per POST, reply as ``application/json`` or a
  request-scoped ``text/event-stream``. No ``initialize`` handshake.
- ``GET /.well-known/oauth-protected-resource/api/mcp`` — RFC 9728 metadata:
  ``resource`` ends with ``/api/mcp``; ``authorization_servers`` non-empty;
  ``scopes_supported`` = ``knowledge:read`` + ``drafts:write`` only
  (``images:generate`` is step-up, ADR 0051 §5).
- ``GET /.well-known/oauth-authorization-server`` — RFC 8414 metadata with
  ``client_id_metadata_document_supported: true`` and
  ``token_endpoint_auth_methods_supported: ["none"]``, and no
  ``registration_endpoint`` (ADR 0053). Clients that see both CIMD signals
  skip Dynamic Client Registration.
- 401 from ``/api/mcp`` carries ``WWW-Authenticate: Bearer
  resource_metadata="…/.well-known/oauth-protected-resource/api/mcp"``.
  Missing scope on a tool → HTTP 403 with ``error="insufficient_scope"``
  and ``scope="<needed>"`` in ``WWW-Authenticate``.
- ``internal.mcp.grants.issue_grant(db, *, user_id, company_id, client_id,
  client_name, scopes: list[str])`` → grant row with ``.id`` (table
  ``oauth_grants``, FK to ``users`` so ``clean_db``'s TRUNCATE … CASCADE
  clears it). The caller commits.
- ``internal.mcp.tokens.create_mcp_access_token(grant)`` → ``(token, exp)``;
  the JWT carries ``type="mcp_access"`` (web ``access`` tokens are refused at
  ``/api/mcp``; MCP tokens are refused by every other ``/api`` route) and
  ``aud`` = the install's MCP URL (RFC 8707).
- ``DELETE /api/auth/me/connected-apps/{grant_id}`` (web bearer) → 204;
  the next MCP call with that grant's token is 401.
- ``sessions.origin`` JSONB: ``{"kind": "mcp", "grant_id", "client_id",
  "client_name", "auto_picks"?}``; ``auto_picks`` = ``{"angle_index",
  "persona", "image_format", "image_approved": bool}``.
- Tool results: ``structuredContent`` carries ``session_id`` + ``status``
  (``running`` | ``awaiting_angle_pick`` | ``awaiting_image_ok`` | ``ready``
  | ``failed`` | ``cancelled``) — result shapes live in ``schemas/mcp.py``
  (``PostDraftState`` union). ``awaiting_angle_pick`` adds the angle-park
  payload incl. ``recommended_angle_index``; ``ready`` adds ``preview`` and
  ``confirm_url`` = ``{web_base_url}/sessions/{id}``. ``approval_token``
  never appears. Guard refusals are tool errors (``isError: true``) whose
  ``structuredContent.reason`` is ``access_denied`` / ``not_found`` /
  ``usage_limit_exceeded``.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

from httpx import Response

from internal.memory.database import open_session
from internal.session.graph import ANGLE_GATE_NODE, IMAGE_PARK_NODE

MCP_PATH = "/api/mcp"
PROTOCOL_VERSION = "2026-07-28"
PRM_PATH = "/.well-known/oauth-protected-resource/api/mcp"
AS_METADATA_PATH = "/.well-known/oauth-authorization-server"
CONNECTED_APP_PATH = "/api/auth/me/connected-apps/{grant_id}"

TEST_CLIENT_ID = "https://claude.example/oauth/client-metadata.json"
TEST_CLIENT_NAME = "Claude"

MCP_TOOLS = frozenset(
    {
        "get_brand_context",
        "start_post_draft",
        "get_post_draft",
        "choose_angle",
        "approve_image",
        "revise_post_draft",
        "cancel_post_draft",
    }
)
"""ADR 0051 §7 — the whole surface. A new tool must update this set."""

SETTLED_STATUSES = frozenset(
    {"awaiting_angle_pick", "awaiting_image_ok", "ready", "failed", "cancelled"}
)

STUB_ANGLES = ["月光下嘅思念", "加班族嘅中秋", "細路仔提燈籠"]
STUB_RECOMMENDED_ANGLE = 1


def rpc_body(method: str, params: dict | None = None, *, rpc_id: int = 1) -> dict:
    """JSON-RPC request carrying the stateless-core ``_meta`` fields."""
    meta = {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "bdd-client", "version": "0.0.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": method,
        "params": {**(params or {}), "_meta": meta},
    }


def rpc_headers(method: str, *, name: str | None = None, token: str | None = None) -> dict:
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name:
        headers["Mcp-Name"] = name
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def parse_rpc(res: Response) -> dict:
    """JSON-RPC response from either reply shape (JSON or request-scoped SSE)."""
    if res.headers.get("content-type", "").startswith("text/event-stream"):
        messages = [
            json.loads(line[len("data:") :].strip())
            for line in res.text.splitlines()
            if line.startswith("data:")
        ]
        final = [m for m in messages if "result" in m or "error" in m]
        assert final, f"SSE reply carried no JSON-RPC response: {res.text}"
        return final[-1]
    return res.json()


def tool_result(res: Response) -> dict:
    """``result`` of a ``tools/call`` reply (``structuredContent`` + ``isError``)."""
    assert res.status_code == 200, res.text
    rpc = parse_rpc(res)
    assert "result" in rpc, f"JSON-RPC error instead of a tool result: {rpc}"
    return rpc["result"]


def structured(result: dict) -> dict:
    content = result.get("structuredContent")
    assert isinstance(content, dict), f"tool result lacks structuredContent: {result}"
    return content


async def issue_mcp_token(
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    scopes: list[str],
    client_id: str = TEST_CLIENT_ID,
    client_name: str = TEST_CLIENT_NAME,
) -> tuple[uuid.UUID, str]:
    """Seed a consented grant and mint its access token, skipping the OAuth dance.

    Deferred import: ``internal.mcp`` does not exist yet — scenarios fail on
    the ModuleNotFoundError, never at collection.
    """
    from internal.mcp.grants import issue_grant
    from internal.mcp.tokens import create_mcp_access_token

    async with open_session() as db:
        grant = await issue_grant(
            db,
            user_id=user_id,
            company_id=company_id,
            client_id=client_id,
            client_name=client_name,
            scopes=scopes,
        )
        await db.commit()
        token, _expires = create_mcp_access_token(grant)
        return grant.id, token


async def fetch_session(session_id: uuid.UUID):
    from internal.memory import repos

    async with open_session() as db:
        return await repos.get_session(db, session_id)


async def add_second_company_session(user_id: uuid.UUID) -> uuid.UUID:
    """Make ``user_id`` owner of a second company and give them a session there."""
    from internal.memory.models import Entity, OrganizationMember, Session

    async with open_session() as db:
        org = Entity(
            entity_type="company",
            slug=f"second-co-{uuid.uuid4().hex[:8]}",
            name="Second Co",
            profile={},
        )
        db.add(org)
        await db.flush()
        db.add(OrganizationMember(user_id=user_id, organization_id=org.id, role="owner"))
        session = Session(user_id=user_id, company_id=org.id, state={})
        db.add(session)
        await db.commit()
        return session.id


class ParkingSessionGraph:
    """Scripted session graph that walks the two ADR 0029/0030 + 0036 parks.

    First ``ainvoke`` (the start turn) → brief with ``STUB_ANGLES`` and
    ``recommended_angle_index``, parked before ``angle_gate``. A resume after
    the pick → drafted caption + plan, parked before ``executor_image_gen``.
    A resume from the image park → primary image, not parked. ``resumes``
    records which park each ``ainvoke(None)`` left, so a scenario can prove
    auto mode never passed the image park.
    """

    def __init__(self) -> None:
        self._values: dict = {}
        self._next: tuple[str, ...] = ()
        self.resumes: list[str] = []

    async def ainvoke(self, graph_input, config):
        values = {**self._values, **dict(graph_input or {})}
        if graph_input is not None:
            values["brief"] = {
                "summary": "中秋推廣",
                "can_do": [],
                "cannot_do": [],
                "angles": list(STUB_ANGLES),
                "recommended_angle_index": STUB_RECOMMENDED_ANGLE,
                "persona": None,
            }
            self._next = (ANGLE_GATE_NODE,)
        elif self._next == (ANGLE_GATE_NODE,):
            self.resumes.append(ANGLE_GATE_NODE)
            values["draft"] = {"caption": "月光光，照住你加班", "hashtags": ["#中秋"], "cta": ""}
            values["image_plan"] = {"prompt": "office window full moon", "format": "single"}
            values["need_image"] = True
            self._next = (IMAGE_PARK_NODE,)
        elif self._next == (IMAGE_PARK_NODE,):
            self.resumes.append(IMAGE_PARK_NODE)
            values["image_url"] = "placeholder://stub-image"
            self._next = ()
        self._values = values
        return values

    async def aupdate_state(self, config, update, as_node=None):
        self._values.update(dict(update or {}))

    async def aget_state(self, config):
        return SimpleNamespace(values=dict(self._values), next=self._next)

    async def adelete_thread(self, thread_id):
        self._values, self._next = {}, ()
