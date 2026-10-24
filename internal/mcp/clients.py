"""Client ID Metadata Documents (ADR 0051 §2, amended by ADR 0053).

The ``client_id`` is an HTTPS URL whose JSON document is the client's
registration. Fetching is SSRF-guarded: https only, no private or loopback
hosts, redirects refused, size and time capped.

``redirect_uri`` is an exact string match against that list, except an
``http`` loopback URI (``localhost``, ``127.0.0.1``, ``[::1]``) may use any
port. RFC 8252 §7.3 requires the port exception for the IP literals; Claude
Code publishes portless ``http://localhost/callback`` and then redirects to
``http://localhost:<ephemeral>/callback`` (ADR 0053). Scheme, host, path,
and query stay exact. The fetch guard is unchanged — loopback is legal only
as a client's redirect, never as a ``client_id`` we fetch.
"""

from __future__ import annotations

import asyncio
import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse

MAX_METADATA_BYTES = 32 * 1024
FETCH_TIMEOUT_SECONDS = 5.0


@dataclass
class ClientMetadataError(Exception):
    message: str

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


async def _host_is_public(host: str) -> bool:
    """Async DNS lookup — sync getaddrinfo would block the event loop.

    Residual risk: httpx re-resolves on connect, so a hostile DNS answer that
    changes between checks and the fetch could still rebind (documented
    hardening gap — pinning the peer IP is left for later).
    """
    host = host.strip().lower()
    if host in {"localhost", "localhost.localdomain"}:
        return False
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        return ip.is_global
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            if not ipaddress.ip_address(addr).is_global:
                return False
        except ValueError:
            return False
    return True


async def validate_client_id(client_id: str) -> str:
    """A client_id must be a public HTTPS URL (CIMD). Returns it stripped."""
    url = (client_id or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ClientMetadataError("client_id must be an https URL")
    if parsed.username or parsed.password:
        raise ClientMetadataError("client_id must not carry credentials")
    if not await _host_is_public(parsed.hostname):
        raise ClientMetadataError("client_id host is not public")
    return url


def validate_client_document(doc: dict, client_id: str) -> dict:
    """The fetched JSON must name this client and list redirect URIs."""
    if not isinstance(doc, dict):
        raise ClientMetadataError("client document is not an object")
    doc_id = str(doc.get("client_id") or "").strip()
    if doc_id != client_id:
        raise ClientMetadataError("client document client_id mismatch")
    uris = doc.get("redirect_uris")
    if not isinstance(uris, list) or not uris or not all(isinstance(u, str) for u in uris):
        raise ClientMetadataError("client document needs a redirect_uris list")
    return doc


# RFC 8252 §7.3 loopback IP literals, plus the ``localhost`` name Claude Code
# actually sends. These are not aliases of each other.
_LOOPBACK_V4 = ipaddress.ip_address("127.0.0.1")
_LOOPBACK_V6 = ipaddress.ip_address("::1")


def _loopback_host_key(hostname: str) -> str | None:
    """``localhost``, ``127.0.0.1``, or ``::1``. Anything else is not loopback."""
    if hostname == "localhost":
        return "localhost"
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return None
    if ip == _LOOPBACK_V4:
        return "127.0.0.1"
    if ip == _LOOPBACK_V6:
        return "::1"
    return None


def _http_loopback_key(uri: str) -> tuple[str, str, str] | None:
    """``(host, path, query)`` for an http loopback redirect, ignoring port.

    ``None`` unless the URI is one we will treat as port-flexible: scheme
    ``http``, no userinfo, no fragment, and a loopback host. Path and query
    stay in the key so they still have to match exactly.
    """
    if not isinstance(uri, str) or any(char in uri for char in "\r\n\\"):
        return None
    parsed = urlparse(uri)
    if parsed.scheme.lower() != "http":
        return None
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        return None
    # urlparse can still report a loopback hostname when userinfo used a trick
    # the username property missed. Refuse the netloc outright.
    if "@" in parsed.netloc or not parsed.hostname:
        return None
    host_key = _loopback_host_key(parsed.hostname)
    if host_key is None:
        return None
    return (host_key, parsed.path, parsed.query)


def redirect_uri_allowed(doc: dict, redirect_uri: str) -> bool:
    """True when ``redirect_uri`` is registered on this client.

    Non-loopback URIs compare as exact strings (ADR 0051). An ``http``
    loopback URI may differ in port only (ADR 0053): ``localhost``,
    ``127.0.0.1``, and ``[::1]`` are matched separately, and a registered
    port does not pin the port the client listens on.
    """
    uris = doc.get("redirect_uris")
    if not isinstance(uris, list):
        return False
    if redirect_uri in uris:
        return True
    requested = _http_loopback_key(redirect_uri)
    if requested is None:
        return False
    return any(
        isinstance(candidate, str) and _http_loopback_key(candidate) == requested
        for candidate in uris
    )


async def fetch_client_metadata(client_id: str) -> dict:
    """Fetch + validate a CIMD document. Raises ClientMetadataError."""
    import json

    import httpx

    await validate_client_id(client_id)
    try:
        async with (
            asyncio.timeout(FETCH_TIMEOUT_SECONDS),
            httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False) as client,
            client.stream("GET", client_id) as response,
        ):
            if response.status_code != 200:
                raise ClientMetadataError(f"client metadata fetch failed ({response.status_code})")
            chunks: list[bytes] = []
            size = 0
            # Stream and cap as we read — aread() would download the whole
            # body first, so the byte cap would never actually bind.
            async for chunk in response.aiter_bytes(8192):
                size += len(chunk)
                if size > MAX_METADATA_BYTES:
                    raise ClientMetadataError("client metadata too large")
                chunks.append(chunk)
            body = b"".join(chunks)
    except TimeoutError as exc:
        raise ClientMetadataError("client metadata fetch timed out") from exc
    except httpx.HTTPError as exc:
        raise ClientMetadataError(f"client metadata fetch failed: {exc}") from exc
    try:
        doc = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ClientMetadataError("client metadata is not JSON") from exc
    return validate_client_document(doc, client_id)
