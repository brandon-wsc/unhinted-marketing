"""OAuth flow logic (internal/mcp/oauth.py + clients.py) — ADR 0051 §2-4.

Pure checks: PKCE S256, client_id URL rules, Client ID Metadata Document
validation. No Postgres, no network (fetching is covered at API level).
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from internal.mcp.clients import (
    ClientMetadataError,
    validate_client_document,
    validate_client_id,
)
from internal.mcp.oauth import pkce_verifier_matches


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


def test_client_id_must_be_https():
    assert validate_client_id("https://chatgpt.com/connector.json") == "https://chatgpt.com/connector.json"
    with pytest.raises(ClientMetadataError):
        validate_client_id("http://example.com/app.json")


def test_client_id_rejects_local_and_private_hosts():
    for url in (
        "https://localhost/app.json",
        "https://127.0.0.1/app.json",
        "https://[::1]/app.json",
        "https://10.0.0.4/app.json",
        "https://192.168.1.2/app.json",
        "https://169.254.169.254/latest/meta.json",
    ):
        with pytest.raises(ClientMetadataError):
            validate_client_id(url)


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


def test_redirect_uri_exact_match():
    doc = {"redirect_uris": ["https://a.example/cb", "http://localhost:3000/cb"]}
    from internal.mcp.clients import redirect_uri_allowed

    assert redirect_uri_allowed(doc, "https://a.example/cb")
    assert not redirect_uri_allowed(doc, "https://a.example/cb/")
    assert not redirect_uri_allowed(doc, "https://a.example/evil")
