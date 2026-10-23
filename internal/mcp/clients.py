"""Client ID Metadata Documents (ADR 0051 §2).

The ``client_id`` is an HTTPS URL whose JSON document is the client's
registration. Fetching is SSRF-guarded: https only, no private or loopback
hosts, redirects refused, size and time capped. ``redirect_uri`` must be an
exact string match against the document's list.
"""

from __future__ import annotations

import ipaddress
import socket
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


def _host_is_public(host: str) -> bool:
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
        infos = socket.getaddrinfo(host, None)
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


def validate_client_id(client_id: str) -> str:
    """A client_id must be a public HTTPS URL (CIMD). Returns it stripped."""
    url = (client_id or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ClientMetadataError("client_id must be an https URL")
    if parsed.username or parsed.password:
        raise ClientMetadataError("client_id must not carry credentials")
    if not _host_is_public(parsed.hostname):
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


def redirect_uri_allowed(doc: dict, redirect_uri: str) -> bool:
    """Exact string match — no prefix or wildcard matching."""
    return redirect_uri in (doc.get("redirect_uris") or [])


async def fetch_client_metadata(client_id: str) -> dict:
    """Fetch + validate a CIMD document. Raises ClientMetadataError."""
    import json

    import httpx

    validate_client_id(client_id)
    try:
        async with (
            httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False) as client,
            client.stream("GET", client_id) as response,
        ):
            if response.status_code != 200:
                raise ClientMetadataError(f"client metadata fetch failed ({response.status_code})")
            body = await response.aread()
            if len(body) > MAX_METADATA_BYTES:
                raise ClientMetadataError("client metadata too large")
    except httpx.HTTPError as exc:
        raise ClientMetadataError(f"client metadata fetch failed: {exc}") from exc
    try:
        doc = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ClientMetadataError("client metadata is not JSON") from exc
    return validate_client_document(doc, client_id)
