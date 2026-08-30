"""SSRF guard for user-supplied LLM base URLs (ADR 0020 §8).

Used by the model-list proxy and credential/model test probes — the server
fetches a URL the org typed. Actual LiteLLM / Pydantic AI traffic also goes to
that base; this helper covers *our* probes. LiteLLM calls inherit the org's
explicit config by design and are not rewritten here.

Guarantees:
- http/https only; no userinfo
- DNS resolved; every address must be global unicast (no loopback / RFC1918 /
  link-local / CGNAT / multicast / unspecified)
- request is pinned to a validated address (DNS-rebinding safe) with the
  original hostname as Host / SNI
- redirects are not followed blindly — each Location is re-validated
- ``trust_env=False`` so env proxy / ambient headers do not attach
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

MAX_URL_LENGTH = 2048
DNS_TIMEOUT_SECONDS = 3.0
BYOK_PROBE_TIMEOUT_SECONDS = 8.0
MAX_REDIRECTS = 3
_ALLOWED_SCHEMES = frozenset({"http", "https"})


class UnsafeUrlError(ValueError):
    """User-supplied URL is not safe to fetch from the server."""


@dataclass(frozen=True)
class PinnedTarget:
    """A URL that has been resolved and pinned to a public address."""

    url: str
    hostname: str
    scheme: str
    port: int
    addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]
    pinned_url: str


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not ip.is_global


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _host_header(hostname: str, scheme: str, port: int) -> str:
    if port == _default_port(scheme):
        return hostname
    return f"{hostname}:{port}"


def _pin_url(url: httpx.URL, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    host = f"[{ip}]" if ip.version == 6 else str(ip)
    return str(url.copy_with(host=host))


def _resolve_addresses(hostname: str, port: int) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Could not resolve hostname {hostname!r}.") from exc
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        raw = sockaddr[0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        key = str(ip)
        if key in seen:
            continue
        seen.add(key)
        addresses.append(ip)
    if not addresses:
        raise UnsafeUrlError(f"Could not resolve hostname {hostname!r}.")
    return tuple(addresses)


def validate_user_url(url: str) -> PinnedTarget:
    """Parse, resolve, and reject private/internal targets. Does not fetch."""
    raw = (url or "").strip()
    if not raw:
        raise UnsafeUrlError("URL is required.")
    if len(raw) > MAX_URL_LENGTH:
        raise UnsafeUrlError("URL is too long.")

    try:
        parts = urlsplit(raw)
        scheme = parts.scheme.lower()
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrlError("URL is invalid.") from exc
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError("URL must be http or https.")
    if parts.username is not None or parts.password is not None:
        raise UnsafeUrlError("URL must not include credentials.")
    hostname = (parts.hostname or "").strip().rstrip(".")
    if not hostname:
        raise UnsafeUrlError("URL must include a hostname.")

    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeUrlError("URL hostname is invalid.") from exc

    port = port or _default_port(scheme)
    if not 1 <= port <= 65535:
        raise UnsafeUrlError("URL port is invalid.")

    literal = _literal_ip(hostname)
    if literal is not None:
        addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...] = (literal,)
    else:
        addresses = _resolve_addresses(hostname, port)

    blocked = [str(ip) for ip in addresses if _blocked_ip(ip)]
    if blocked:
        raise UnsafeUrlError("URL resolves to a private or internal address.")

    parsed = httpx.URL(raw)
    pinned = _pin_url(parsed, addresses[0])
    return PinnedTarget(
        url=raw,
        hostname=hostname,
        scheme=scheme,
        port=port,
        addresses=addresses,
        pinned_url=pinned,
    )


async def validate_user_url_async(url: str) -> PinnedTarget:
    """Async wrapper so DNS resolution can time out."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(validate_user_url, url),
            timeout=DNS_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise UnsafeUrlError("Timed out resolving the URL hostname.") from exc


async def guarded_request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    json: Any = None,
    content: bytes | None = None,
    timeout: float = BYOK_PROBE_TIMEOUT_SECONDS,
    transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
) -> httpx.Response:
    """GET/POST a user-supplied URL with SSRF pinning and re-validated redirects.

    Caller-supplied headers only (e.g. Authorization). The response body is fully
    read before return so the client can close.
    """
    if json is not None and content is not None:
        raise ValueError("Pass json or content, not both.")

    current = url
    extra = {str(k): str(v) for k, v in (headers or {}).items()}
    # Never let a caller override Host — pinning owns it.
    extra.pop("Host", None)
    extra.pop("host", None)

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(timeout),
        "follow_redirects": False,
        "trust_env": False,
        "headers": {},
    }
    if transport is not None:
        client_kwargs["transport"] = transport

    async with httpx.AsyncClient(**client_kwargs) as client:
        for hop in range(MAX_REDIRECTS + 1):
            target = await validate_user_url_async(current)
            request_headers = {
                **extra,
                "Host": _host_header(target.hostname, target.scheme, target.port),
            }
            extensions: dict[str, Any] = {}
            if target.scheme == "https":
                extensions["sni_hostname"] = target.hostname

            response = await client.request(
                method.upper(),
                target.pinned_url,
                headers=request_headers,
                json=json,
                content=content,
                extensions=extensions,
            )
            await response.aread()
            if response.has_redirect_location:
                if hop == MAX_REDIRECTS:
                    raise UnsafeUrlError("Too many redirects.")
                location = response.headers.get("location")
                if not location:
                    return response
                current = str(httpx.URL(current).join(location))
                json = None
                content = None
                continue
            return response

    raise UnsafeUrlError("Too many redirects.")
