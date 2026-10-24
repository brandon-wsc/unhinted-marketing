"""OAuth flow logic (internal/mcp/oauth.py + clients.py) — ADR 0051 §2-4.

Pure checks: PKCE S256, client_id URL rules, Client ID Metadata Document
validation. No Postgres, no network (fetching is covered at API level).
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from internal.instance.config import InstanceSnapshot
from internal.mcp.clients import (
    ClientMetadataError,
    redirect_uri_allowed,
    validate_client_document,
    validate_client_id,
)
from internal.mcp.grants import KNOWN_SCOPES
from internal.mcp.oauth import (
    DEFAULT_SCOPES,
    STEP_UP_SCOPES,
    OAuthError,
    merge_consent_scopes,
    parse_scope,
    pkce_verifier_matches,
    step_up_scopes_for,
)


def _verifier_for(challenge: str) -> str:
    """Invert S256: we can't, so build a challenge from a verifier instead."""
    raise AssertionError("not used")


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def test_pkce_s256_verifier_matches():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_verifier_matches(verifier, _challenge(verifier))


def test_pkce_rejects_wrong_verifier():
    assert not pkce_verifier_matches("wrong", _challenge("right"))


@pytest.mark.asyncio
async def test_client_id_must_be_https():
    assert (
        await validate_client_id("https://chatgpt.com/connector.json")
        == "https://chatgpt.com/connector.json"
    )
    with pytest.raises(ClientMetadataError):
        await validate_client_id("http://example.com/app.json")


@pytest.mark.asyncio
async def test_client_id_rejects_local_and_private_hosts():
    for url in (
        "https://localhost/app.json",
        "https://127.0.0.1/app.json",
        "https://[::1]/app.json",
        "https://10.0.0.4/app.json",
        "https://192.168.1.2/app.json",
        "https://169.254.169.254/latest/meta.json",
    ):
        with pytest.raises(ClientMetadataError):
            await validate_client_id(url)


def test_client_document_needs_redirect_uris_list():
    with pytest.raises(ClientMetadataError):
        validate_client_document({"client_name": "x"}, "https://a.example/app.json")
    doc = validate_client_document(
        {
            "client_id": "https://a.example/app.json",
            "client_name": "A",
            "redirect_uris": ["https://a.example/cb"],
        },
        "https://a.example/app.json",
    )
    assert doc["redirect_uris"] == ["https://a.example/cb"]


def test_client_document_client_id_must_match():
    with pytest.raises(ClientMetadataError):
        validate_client_document(
            {"client_id": "https://evil.example/x.json", "redirect_uris": []},
            "https://a.example/app.json",
        )


def test_redirect_uri_exact_match_off_loopback():
    """https and other non-loopback URIs stay byte-for-byte (ADR 0051)."""
    doc = {"redirect_uris": ["https://a.example/cb", "http://localhost:3000/cb"]}

    assert redirect_uri_allowed(doc, "https://a.example/cb")
    assert not redirect_uri_allowed(doc, "https://a.example/cb/")
    assert not redirect_uri_allowed(doc, "https://a.example/evil")
    assert not redirect_uri_allowed(doc, "https://a.example:443/cb")
    # The loopback entry still matches its own string, and any other port
    # on that same host and path (ADR 0053). A different loopback host does not.
    assert redirect_uri_allowed(doc, "http://localhost:3000/cb")
    assert redirect_uri_allowed(doc, "http://localhost:4545/cb")
    assert not redirect_uri_allowed(doc, "http://127.0.0.1:4545/cb")
    assert not redirect_uri_allowed(doc, "http://localhost:4545/other")


# Published 2026-10-24 at https://claude.ai/oauth/claude-code-client-metadata.
# The CLI then sends http://localhost:<ephemeral-port>/callback (RFC 8252 §7.3
# for the IP literal; Claude's connector docs ask servers to apply the same
# port-agnostic match to the localhost name the CLI actually uses).
_CLAUDE_CODE_CIMD = {
    "redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"],
}


def test_claude_code_ephemeral_localhost_callback_is_allowed():
    assert redirect_uri_allowed(_CLAUDE_CODE_CIMD, "http://localhost/callback")
    assert redirect_uri_allowed(_CLAUDE_CODE_CIMD, "http://localhost:3118/callback")
    assert redirect_uri_allowed(_CLAUDE_CODE_CIMD, "http://127.0.0.1:3118/callback")
    assert redirect_uri_allowed(_CLAUDE_CODE_CIMD, "HTTP://LOCALHOST:3118/callback")


def test_claude_code_callback_rejects_lookalikes_and_other_parts():
    rejected = (
        "http://localhost:3118/callback/",
        "http://localhost:3118/callback/extra",
        "http://localhost:3118/Callback",
        "https://localhost:3118/callback",
        "http://localhost:3118/callback?next=1",
        "http://localhost:3118/callback#frag",
        "http://user@localhost:3118/callback",
        "http://localhost.evil.test:3118/callback",
        "http://localhost.localdomain:3118/callback",
        "http://127.0.0.1.evil.test/callback",
        "http://127.0.0.2:3118/callback",
        "http://[::1]:3118/callback",
        "http://2130706433:3118/callback",
        "http://localhost:3118\\@evil.test/callback",
        # Malformed input must return False, never raise through to a 500.
        "http://[::1/callback",
        "http://localhost:notaport/callback",
        "http://localhost:99999/callback",
        "http://localhost:/callback",
        # ;params are part of the path — they stay exact too.
        "http://localhost:3118/callback;extra",
        # A literal fragment/query mark is not the same URI as its absence.
        "http://localhost:3118/callback#",
        "http://localhost:3118/callback?",
        # Characters the URL parser strips or refuses outright.
        "http://local\thost:3118/callback",
        "http://local host:3118/callback",
    )
    for uri in rejected:
        assert not redirect_uri_allowed(_CLAUDE_CODE_CIMD, uri), uri


def test_loopback_port_exception_keeps_path_query_and_host():
    """A registered port does not pin the request port; nothing else moves."""
    doc = {"redirect_uris": ["http://127.0.0.1:3000/cb?x=1"]}
    assert redirect_uri_allowed(doc, "http://127.0.0.1:4545/cb?x=1")
    assert redirect_uri_allowed(doc, "http://127.0.0.1/cb?x=1")
    assert not redirect_uri_allowed(doc, "http://127.0.0.1:4545/cb")
    assert not redirect_uri_allowed(doc, "http://127.0.0.1:4545/cb?x=2")
    assert not redirect_uri_allowed(doc, "http://localhost:4545/cb?x=1")

    v6 = {"redirect_uris": ["http://[::1]/callback"]}
    assert redirect_uri_allowed(v6, "http://[::1]:3118/callback")
    assert redirect_uri_allowed(v6, "http://[0:0:0:0:0:0:0:1]:3118/callback")
    assert not redirect_uri_allowed(v6, "http://[::ffff:127.0.0.1]:3118/callback")
    assert not redirect_uri_allowed(v6, "http://127.0.0.1:3118/callback")

    # ;params live inside the path — they take the port exception like any
    # other exact path, and a params difference is still a mismatch.
    params = {"redirect_uris": ["http://localhost/cb;keep"]}
    assert redirect_uri_allowed(params, "http://localhost:4545/cb;keep")
    assert not redirect_uri_allowed(params, "http://localhost:4545/cb")
    assert not redirect_uri_allowed(params, "http://localhost:4545/cb;other")


def test_https_callback_stays_exact_including_grok():
    """Grok's CIMD (fetched 2026-10-24) is https with a trailing slash — exact.

    ``https://localhost`` does not get the loopback port exception; that
    exception is ``http`` only (RFC 8252).
    """
    doc = {
        "redirect_uris": [
            "https://grok.com/connectors-oauth-exchange-code/",
            "https://console.x.ai/connectors-oauth-exchange-code/",
        ]
    }
    assert redirect_uri_allowed(doc, "https://grok.com/connectors-oauth-exchange-code/")
    assert not redirect_uri_allowed(doc, "https://grok.com/connectors-oauth-exchange-code")
    assert not redirect_uri_allowed(doc, "https://grok.com/connectors-oauth-exchange-code/extra")
    assert not redirect_uri_allowed(doc, "https://evil.example/connectors-oauth-exchange-code/")
    hosted = {"redirect_uris": ["https://claude.ai/api/mcp/auth_callback"]}
    assert redirect_uri_allowed(hosted, "https://claude.ai/api/mcp/auth_callback")
    assert not redirect_uri_allowed(hosted, "https://claude.ai:443/api/mcp/auth_callback")
    https_loopback = {"redirect_uris": ["https://localhost/callback"]}
    assert redirect_uri_allowed(https_loopback, "https://localhost/callback")
    assert not redirect_uri_allowed(https_loopback, "https://localhost:3118/callback")


def test_authorization_server_metadata_advertises_cimd(monkeypatch):
    """Claude selects CIMD only when both of these are present; no DCR endpoint."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from cmd.api.routes.mcp import discovery_router

    monkeypatch.setattr(
        "cmd.api.routes.mcp.get_snapshot",
        lambda: InstanceSnapshot(web_base_url="https://install.example"),
    )
    app = FastAPI()
    app.include_router(discovery_router)
    response = TestClient(app).get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    assert response.json() == {
        "issuer": "https://install.example",
        "authorization_endpoint": "https://install.example/api/oauth/authorize",
        "token_endpoint": "https://install.example/api/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "client_id_metadata_document_supported": True,
        "scopes_supported": sorted(KNOWN_SCOPES),
    }
    assert "registration_endpoint" not in response.json()

def test_default_scopes_exclude_images_step_up():
    """PRM defaults stay without images:generate (ADR 0051 §5)."""
    assert "images:generate" in STEP_UP_SCOPES
    assert "images:generate" not in DEFAULT_SCOPES
    assert set(DEFAULT_SCOPES) == KNOWN_SCOPES - STEP_UP_SCOPES


def test_parse_scope_absent_uses_prm_defaults():
    assert parse_scope(None) == list(DEFAULT_SCOPES)
    assert parse_scope("") == list(DEFAULT_SCOPES)


def test_parse_scope_rejects_unknown():
    with pytest.raises(OAuthError) as exc:
        parse_scope("drafts:write publish:write")
    assert exc.value.error == "invalid_scope"


def test_step_up_scopes_for_omits_already_requested():
    assert step_up_scopes_for(["knowledge:read", "drafts:write"]) == ["images:generate"]
    assert step_up_scopes_for(["knowledge:read", "drafts:write", "images:generate"]) == []


def test_merge_consent_scopes_opt_in_adds_images():
    requested = ["drafts:write", "knowledge:read"]
    assert merge_consent_scopes(requested, []) == requested
    assert merge_consent_scopes(requested, None) == requested
    assert merge_consent_scopes(requested, ["images:generate"]) == [
        "drafts:write",
        "images:generate",
        "knowledge:read",
    ]


def test_merge_consent_scopes_rejects_unknown_and_non_step_up():
    with pytest.raises(OAuthError) as unknown:
        merge_consent_scopes(["drafts:write"], ["publish:write"])
    assert unknown.value.error == "invalid_scope"
    with pytest.raises(OAuthError) as not_step:
        merge_consent_scopes(["knowledge:read"], ["drafts:write"])
    assert not_step.value.error == "invalid_scope"
