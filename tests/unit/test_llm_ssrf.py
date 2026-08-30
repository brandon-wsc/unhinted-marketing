"""SSRF guard for user-supplied LLM base URLs (no live network)."""

from __future__ import annotations

import ipaddress

import httpx
import pytest

from internal.llm.ssrf import (
    MAX_REDIRECTS,
    UnsafeUrlError,
    guarded_request,
    validate_user_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/v1",
        "http://10.0.0.1/v1",
        "http://10.1.2.3/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0/",
        "http://255.255.255.255/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://100.64.0.1/",
    ],
)
def test_validate_blocks_private_literals(url: str) -> None:
    with pytest.raises(UnsafeUrlError, match="private or internal"):
        validate_user_url(url)


def test_validate_blocks_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "internal.llm.ssrf._resolve_addresses",
        lambda *_a, **_k: (ipaddress.ip_address("127.0.0.1"),),
    )
    with pytest.raises(UnsafeUrlError, match="private or internal"):
        validate_user_url("http://localhost/v1")


def test_validate_blocks_credentials() -> None:
    with pytest.raises(UnsafeUrlError, match="credentials"):
        validate_user_url("https://user:pass@example.com/v1")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "file:///etc/passwd",
        "ftp://example.com/",
        "https://",
        "not-a-url",
        "http://example.com:99999/",
    ],
)
def test_validate_rejects_malformed(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_user_url(url)


def test_validate_accepts_public_literal() -> None:
    target = validate_user_url("https://1.1.1.1/v1")
    assert target.hostname == "1.1.1.1"
    assert target.pinned_url.startswith("https://1.1.1.1")
    assert target.addresses == (ipaddress.ip_address("1.1.1.1"),)


def test_validate_pins_resolved_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("internal.llm.ssrf._resolve_addresses", lambda *_a, **_k: (
        ipaddress.ip_address("1.1.1.1"),
    ))
    target = validate_user_url("https://openrouter.ai/api/v1")
    assert target.hostname == "openrouter.ai"
    assert "1.1.1.1" in target.pinned_url
    assert "openrouter.ai" not in httpx.URL(target.pinned_url).host


def test_validate_rejects_mixed_private_record(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "internal.llm.ssrf._resolve_addresses",
        lambda *_a, **_k: (
            ipaddress.ip_address("1.1.1.1"),
            ipaddress.ip_address("10.0.0.1"),
        ),
    )
    with pytest.raises(UnsafeUrlError, match="private or internal"):
        validate_user_url("https://evil.example/v1")


def test_validate_unresolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_hostname: str, _port: int) -> tuple:
        raise UnsafeUrlError("Could not resolve hostname 'nope.invalid'.")

    monkeypatch.setattr("internal.llm.ssrf._resolve_addresses", boom)
    with pytest.raises(UnsafeUrlError, match="Could not resolve"):
        validate_user_url("https://nope.invalid/v1")


@pytest.mark.asyncio
async def test_guarded_request_pins_host_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("internal.llm.ssrf._resolve_addresses", lambda *_a, **_k: (
        ipaddress.ip_address("1.1.1.1"),
    ))
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers.get("host")))
        return httpx.Response(200, json={"data": []})

    res = await guarded_request(
        "GET",
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": "Bearer sk-test", "Host": "evil.internal"},
        transport=httpx.MockTransport(handler),
    )
    assert res.status_code == 200
    assert seen == [("1.1.1.1", "openrouter.ai")]


@pytest.mark.asyncio
async def test_guarded_request_blocks_redirect_to_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("internal.llm.ssrf._resolve_addresses", lambda *_a, **_k: (
        ipaddress.ip_address("1.1.1.1"),
    ))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"})

    with pytest.raises(UnsafeUrlError, match="private or internal"):
        await guarded_request(
            "GET",
            "https://openrouter.ai/api/v1",
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.asyncio
async def test_guarded_request_revalidates_relative_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("internal.llm.ssrf._resolve_addresses", lambda *_a, **_k: (
        ipaddress.ip_address("1.1.1.1"),
    ))
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.headers["host"])
        if request.url.path.rstrip("/") == "/v1":
            return httpx.Response(302, headers={"Location": "/v2/models"})
        return httpx.Response(200, json={"ok": True})

    res = await guarded_request(
        "GET",
        "https://openrouter.ai/v1",
        transport=httpx.MockTransport(handler),
    )
    assert res.status_code == 200
    assert hosts == ["openrouter.ai", "openrouter.ai"]
    assert res.json() == {"ok": True}


@pytest.mark.asyncio
async def test_guarded_request_too_many_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("internal.llm.ssrf._resolve_addresses", lambda *_a, **_k: (
        ipaddress.ip_address("1.1.1.1"),
    ))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "/next"})

    with pytest.raises(UnsafeUrlError, match="Too many redirects"):
        await guarded_request(
            "GET",
            "https://openrouter.ai/v1",
            transport=httpx.MockTransport(handler),
        )


def test_max_redirects_constant() -> None:
    assert MAX_REDIRECTS == 3
