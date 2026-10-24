"""Step defs for features/mcp.feature — ADR 0051 remote MCP server.

The invented contract (routes, seams, result shapes) is documented in
tests/api/mcp_helpers.py. Grants are seeded through the ``issue_grant`` seam
so scenarios skip the OAuth dance; the consent + token endpoints get their
own unit tests. Steps stay sync (pytest-bdd); async work goes through
``api.run``.
"""

from __future__ import annotations

import asyncio
import re
import uuid

from pytest_bdd import given, parsers, scenarios, then, when

from internal.memory.database import open_session
from internal.memory.models import LlmCallRecord, Session
from internal.session.graph import ANGLE_GATE_NODE, set_session_graph
from tests.api.helpers import auth_header, join_org, register_user, seed_preview_session
from tests.api.mcp_helpers import (
    CONNECTED_APP_PATH,
    MCP_TOOLS,
    PRM_PATH,
    SETTLED_STATUSES,
    STUB_ANGLES,
    STUB_RECOMMENDED_ANGLE,
    TEST_CLIENT_ID,
    TEST_CLIENT_NAME,
    ParkingSessionGraph,
    add_second_company_session,
    fetch_session,
    issue_mcp_token,
    parse_rpc,
    structured,
    tool_result,
)

scenarios("../features/mcp.feature")

SEEDED_APPROVAL_TOKEN = "test-approval-token-001"


def _register(api, bdd_ctx, email: str) -> None:
    body = api.run(register_user(api.client, email=email))
    bdd_ctx["user_id"] = uuid.UUID(body["user"]["id"])
    bdd_ctx["company_id"] = uuid.UUID(body["user"]["organizations"][0]["id"])
    bdd_ctx["access_token"] = body["access_token"]


def _grant(api, bdd_ctx, scopes: str) -> None:
    grant_id, token = api.run(
        issue_mcp_token(
            user_id=bdd_ctx["user_id"],
            company_id=bdd_ctx["company_id"],
            scopes=scopes.split(),
        )
    )
    bdd_ctx["grant_id"] = grant_id
    bdd_ctx["mcp_token"] = token


def _challenge(bdd_ctx) -> str:
    return bdd_ctx["res"].headers.get("www-authenticate", "")


# --- members + grants ---------------------------------------------------------


@given("a member with a web session")
def member_with_web_session(api, bdd_ctx) -> None:
    _register(api, bdd_ctx, "bdd-mcp-web@example.com")


@given(parsers.parse('a member with an MCP grant for "{scopes}"'))
def member_with_grant(api, bdd_ctx, scopes: str) -> None:
    _register(api, bdd_ctx, "bdd-mcp@example.com")
    _grant(api, bdd_ctx, scopes)


@given(parsers.parse('the member holds an MCP grant for "{scopes}"'))
def member_holds_grant(api, bdd_ctx, scopes: str) -> None:
    _grant(api, bdd_ctx, scopes)


@given("a capped member who has used their monthly tokens")
def capped_member(api, bdd_ctx) -> None:
    owner = api.run(register_user(api.client, email="bdd-mcp-owner@example.com"))
    company_id = uuid.UUID(owner["user"]["organizations"][0]["id"])
    _register(api, bdd_ctx, "bdd-mcp-capped@example.com")

    async def cap() -> None:
        async with open_session() as db:
            membership = await join_org(
                db, user_id=bdd_ctx["user_id"], company_id=company_id, role="member"
            )
            membership.monthly_token_limit = 100
            db.add(
                LlmCallRecord(
                    caller="node:reviewer",
                    node="reviewer",
                    kind="chat_json",
                    tier="strong",
                    model="gpt-test",
                    status="ok",
                    latency_ms=10,
                    prompt_tokens=100,
                    completion_tokens=50,
                    total_tokens=150,
                    system_prompt="sys",
                    user_prompt="usr",
                    response_text="{}",
                    parse_ok=True,
                    fallback_used=False,
                    user_id=bdd_ctx["user_id"],
                    company_id=company_id,
                    key_source="env",
                )
            )
            await db.commit()

    api.run(cap())
    bdd_ctx["company_id"] = company_id


@given("a teammate in the same company has a session")
def teammate_has_session(api, bdd_ctx) -> None:
    mate = api.run(register_user(api.client, email="bdd-mcp-mate@example.com"))

    async def join() -> None:
        async with open_session() as db:
            await join_org(
                db, user_id=uuid.UUID(mate["user"]["id"]), company_id=bdd_ctx["company_id"]
            )

    api.run(join())
    res = api.post(
        "/api/sessions",
        json={"company_id": str(bdd_ctx["company_id"])},
        headers=auth_header(mate["access_token"]),
    )
    assert res.status_code == 201, res.text
    bdd_ctx["other_session_id"] = uuid.UUID(res.json()["id"])


@given("the member also owns a session in a second company")
def member_owns_second_company_session(api, bdd_ctx) -> None:
    bdd_ctx["other_session_id"] = api.run(add_second_company_session(bdd_ctx["user_id"]))


# --- sessions + graph ---------------------------------------------------------


@given("the session graph parks at both gates")
def graph_parks_at_both_gates(bdd_ctx) -> None:
    bdd_ctx["graph"] = ParkingSessionGraph()
    set_session_graph(bdd_ctx["graph"])


@given("the member has a session parked at image OK")
def member_session_parked_at_image(api, bdd_ctx) -> None:
    async def seed() -> uuid.UUID:
        async with open_session() as db:
            session = Session(
                user_id=bdd_ctx["user_id"],
                company_id=bdd_ctx["company_id"],
                state={
                    "awaiting_image_ok": True,
                    "draft": {"caption": "pending", "hashtags": [], "cta": ""},
                },
            )
            db.add(session)
            await db.commit()
            return session.id

    bdd_ctx["session_id"] = api.run(seed())


@given("the member has a preview-ready session")
def member_preview_ready_session(api, bdd_ctx) -> None:
    async def seed() -> uuid.UUID:
        async with open_session() as db:
            return await seed_preview_session(
                db,
                user_id=bdd_ctx["user_id"],
                company_id=bdd_ctx["company_id"],
                approval_token=SEEDED_APPROVAL_TOKEN,
            )

    bdd_ctx["session_id"] = api.run(seed())


# --- requests -----------------------------------------------------------------


@when("an MCP client lists tools without a token")
def list_tools_without_token(api, bdd_ctx) -> None:
    bdd_ctx["res"] = api.mcp_list_tools(None)


@when("the member lists MCP tools with the web token")
def list_tools_with_web_token(api, bdd_ctx) -> None:
    bdd_ctx["res"] = api.mcp_list_tools(bdd_ctx["access_token"])


@when("the client lists MCP tools")
def list_tools(api, bdd_ctx) -> None:
    bdd_ctx["res"] = api.mcp_list_tools(bdd_ctx["mcp_token"])


@when("the client fetches the protected resource metadata")
def fetch_prm(api, bdd_ctx) -> None:
    bdd_ctx["res"] = api.get(PRM_PATH)


@when(parsers.parse('the MCP token requests "{method} {path}"'))
def mcp_token_requests_web_route(api, bdd_ctx, method: str, path: str) -> None:
    bdd_ctx["res"] = api.request(method, path, headers=auth_header(bdd_ctx["mcp_token"]))


@when("the member revokes the connected app on the web")
def revoke_connected_app(api, bdd_ctx) -> None:
    bdd_ctx["revoke_res"] = api.request(
        "DELETE",
        CONNECTED_APP_PATH.format(grant_id=bdd_ctx["grant_id"]),
        headers=auth_header(bdd_ctx["access_token"]),
    )


@when("the client approves the image")
def approve_image(api, bdd_ctx) -> None:
    bdd_ctx["res"] = api.mcp_call(
        "approve_image", {"session_id": str(bdd_ctx["session_id"])}, bdd_ctx["mcp_token"]
    )


@when(parsers.parse('the client starts a post draft "{brief}"'))
def start_post_draft(api, bdd_ctx, brief: str) -> None:
    bdd_ctx["res"] = api.mcp_call("start_post_draft", {"brief": brief}, bdd_ctx["mcp_token"])


@when(parsers.parse('the client starts an auto post draft "{brief}"'))
def start_auto_post_draft(api, bdd_ctx, brief: str) -> None:
    bdd_ctx["res"] = api.mcp_call(
        "start_post_draft", {"brief": brief, "auto": True}, bdd_ctx["mcp_token"]
    )


@when("the client gets the teammate's post draft")
@when("the client gets that second-company post draft")
def get_other_post_draft(api, bdd_ctx) -> None:
    bdd_ctx["res"] = api.mcp_call(
        "get_post_draft", {"session_id": str(bdd_ctx["other_session_id"])}, bdd_ctx["mcp_token"]
    )


@when("the client gets that post draft")
def get_post_draft(api, bdd_ctx) -> None:
    bdd_ctx["res"] = api.mcp_call(
        "get_post_draft", {"session_id": str(bdd_ctx["session_id"])}, bdd_ctx["mcp_token"]
    )
    bdd_ctx["draft"] = structured(tool_result(bdd_ctx["res"]))


@when("the client polls the draft until it settles")
def poll_until_settled(api, bdd_ctx) -> None:
    session_id = structured(tool_result(bdd_ctx["res"]))["session_id"]
    bdd_ctx["session_id"] = uuid.UUID(session_id)
    for _ in range(100):
        res = api.mcp_call("get_post_draft", {"session_id": session_id}, bdd_ctx["mcp_token"])
        draft = structured(tool_result(res))
        if draft["status"] in SETTLED_STATUSES:
            bdd_ctx["draft"] = draft
            return
        api.run(asyncio.sleep(0.02))
    raise AssertionError(f"draft never settled; last status {draft['status']!r}")


# --- assertions ---------------------------------------------------------------


@then(parsers.parse("the response status is {code:d}"))
def response_status(bdd_ctx, code: int) -> None:
    assert bdd_ctx["res"].status_code == code, bdd_ctx["res"].text


@then(parsers.parse("the revoke response status is {code:d}"))
def revoke_status(bdd_ctx, code: int) -> None:
    assert bdd_ctx["revoke_res"].status_code == code, bdd_ctx["revoke_res"].text


@then("the challenge points at the protected resource metadata")
def challenge_points_at_prm(bdd_ctx) -> None:
    challenge = _challenge(bdd_ctx)
    assert challenge.lower().startswith("bearer"), challenge
    assert "resource_metadata=" in challenge and PRM_PATH in challenge, challenge


@then(parsers.parse('the challenge asks for scope "{scope}"'))
def challenge_asks_for_scope(bdd_ctx, scope: str) -> None:
    challenge = _challenge(bdd_ctx)
    assert 'error="insufficient_scope"' in challenge, challenge
    match = re.search(r'scope="([^"]*)"', challenge)
    assert match and scope in match.group(1).split(), challenge


@then("the metadata names the MCP endpoint as the resource")
def prm_resource(bdd_ctx) -> None:
    assert bdd_ctx["res"].json()["resource"].endswith("/api/mcp")


@then("the metadata names an authorization server")
def prm_authorization_server(bdd_ctx) -> None:
    servers = bdd_ctx["res"].json().get("authorization_servers")
    assert isinstance(servers, list) and servers


@then(parsers.parse('the default scopes are "{scopes}"'))
def prm_default_scopes(bdd_ctx, scopes: str) -> None:
    assert set(bdd_ctx["res"].json()["scopes_supported"]) == set(scopes.split())


@then("the tools are exactly the ADR 0051 surface")
def tools_are_adr_surface(bdd_ctx) -> None:
    tools = parse_rpc(bdd_ctx["res"])["result"]["tools"]
    assert {t["name"] for t in tools} == MCP_TOOLS


@then("no tool name mentions publish or confirm")
def no_publish_tool(bdd_ctx) -> None:
    for tool in parse_rpc(bdd_ctx["res"])["result"]["tools"]:
        assert not re.search(r"publish|confirm", tool["name"], re.IGNORECASE), tool["name"]


@then(parsers.parse('the tool result has a session id and status "{status}"'))
def tool_result_session_and_status(bdd_ctx, status: str) -> None:
    content = structured(tool_result(bdd_ctx["res"]))
    bdd_ctx["session_id"] = uuid.UUID(content["session_id"])
    assert content["status"] == status


@then("the session belongs to the member and the granted company")
def session_belongs_to_grant(api, bdd_ctx) -> None:
    session = api.run(fetch_session(bdd_ctx["session_id"]))
    assert session is not None
    assert session.user_id == bdd_ctx["user_id"]
    assert session.company_id == bdd_ctx["company_id"]


@then("the session origin records the MCP client")
def session_origin_records_client(api, bdd_ctx) -> None:
    origin = api.run(fetch_session(bdd_ctx["session_id"])).origin
    assert origin["kind"] == "mcp"
    assert origin["grant_id"] == str(bdd_ctx["grant_id"])
    assert origin["client_id"] == TEST_CLIENT_ID
    assert origin["client_name"] == TEST_CLIENT_NAME


@then(parsers.parse('the tool call is refused with reason "{reason}"'))
def tool_call_refused(bdd_ctx, reason: str) -> None:
    result = tool_result(bdd_ctx["res"])
    assert result.get("isError") is True, result
    assert structured(result)["reason"] == reason


@then(parsers.parse('the draft status is "{status}"'))
def draft_status(bdd_ctx, status: str) -> None:
    assert bdd_ctx["draft"]["status"] == status, bdd_ctx["draft"]


@then("the result offers the angles with a recommended angle index")
def result_offers_angles(bdd_ctx) -> None:
    draft = bdd_ctx["draft"]
    assert draft["angles"] == STUB_ANGLES
    assert draft["recommended_angle_index"] == STUB_RECOMMENDED_ANGLE


@then("the graph never resumed past the image park")
def graph_never_passed_image_park(bdd_ctx) -> None:
    assert bdd_ctx["graph"].resumes == [ANGLE_GATE_NODE]


@then("the session origin records the recommended angle as an auto pick")
def origin_records_auto_pick(api, bdd_ctx) -> None:
    picks = api.run(fetch_session(bdd_ctx["session_id"])).origin["auto_picks"]
    assert picks["angle_index"] == STUB_RECOMMENDED_ANGLE
    assert picks["image_approved"] is False


@then("the result carries a confirm url for the session")
def result_carries_confirm_url(bdd_ctx) -> None:
    assert bdd_ctx["draft"]["confirm_url"].endswith(f"/sessions/{bdd_ctx['session_id']}")


@then("the reply never contains the approval token")
def reply_never_contains_approval_token(bdd_ctx) -> None:
    assert SEEDED_APPROVAL_TOKEN not in bdd_ctx["res"].text
    assert "approval_token" not in bdd_ctx["res"].text
