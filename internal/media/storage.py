"""Media asset storage facade (ADR 0024 / 0025).

Callers use ``put_bytes`` / ``persist_generated_image`` / ``media_object_key``.
Store-backed rows persist the object key; ``resolve_stored_url`` derives a
browser URL at read. Backend is local disk when ``DEPLOYMENT_MODE=onprem``
and AWS S3 when ``cloud``.
"""

from __future__ import annotations

import base64
import secrets

from internal.config import settings
from internal.media.backends import (
    MediaStorageError,
    assert_media_store_ready,
    local_media_path,
    normalize_key,
    resolve_media_store,
)

MAX_MEDIA_BYTES = 10 * 1024 * 1024
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"

__all__ = [
    "MAX_MEDIA_BYTES",
    "MediaStorageError",
    "assert_media_store_ready",
    "is_stored_image_ref",
    "local_media_path",
    "media_object_key",
    "parse_data_url",
    "persist_generated_image",
    "public_url",
    "put_bytes",
    "resolve_stored_url",
]


def parse_data_url(data_url: str) -> tuple[bytes, str]:
    if not data_url.startswith("data:"):
        raise MediaStorageError("Expected a data: URL")
    header, _, payload = data_url.partition(",")
    if not payload:
        raise MediaStorageError("Malformed data: URL (missing payload)")
    # data:image/png;base64
    meta = header[5:]
    content_type = meta.split(";", 1)[0] or "application/octet-stream"
    if ";base64" not in meta:
        raise MediaStorageError("Only base64 data: URLs are supported")
    if len(payload) * 3 // 4 > MAX_MEDIA_BYTES:
        raise MediaStorageError("Image too large (max 10MB)")
    try:
        raw = base64.b64decode(payload, validate=False)
    except Exception as exc:
        raise MediaStorageError("Invalid base64 in data: URL") from exc
    if len(raw) > MAX_MEDIA_BYTES:
        raise MediaStorageError("Image too large (max 10MB)")
    return raw, content_type


async def put_bytes(*, key: str, data: bytes, content_type: str) -> str:
    """Upload bytes via the resolved store; return a browser-fetchable URL."""
    return await resolve_media_store().put_bytes(
        key=key, data=data, content_type=content_type
    )


_API_MEDIA_PREFIX = "/api/media/"


def public_url(key: str) -> str:
    """Browser-facing URL for a store object key (current origin / CDN)."""
    return resolve_media_store().public_url(key)


def _peel_key(candidate: str) -> str | None:
    raw = candidate.split("?", 1)[0].split("#", 1)[0].strip()
    if not raw:
        return None
    try:
        return normalize_key(raw)
    except MediaStorageError:
        return None


def extract_store_key(stored: str) -> str | None:
    """Peel an object key out of a baked URL for *our* store, else None."""
    raw = (stored or "").strip()
    if not raw:
        return None
    if raw.startswith(_API_MEDIA_PREFIX):
        return _peel_key(raw[len(_API_MEDIA_PREFIX) :])
    idx = raw.find(_API_MEDIA_PREFIX)
    if idx != -1:
        return _peel_key(raw[idx + len(_API_MEDIA_PREFIX) :])
    base = (settings.s3_public_base_url or "").strip().rstrip("/")
    if base and (raw.startswith(base + "/") or raw.startswith(base + "?")):
        return _peel_key(raw[len(base) :].lstrip("/"))
    bucket = (settings.s3_bucket or "").strip()
    region = settings.s3_region or "us-east-1"
    if bucket:
        prefix = f"https://{bucket}.s3.{region}.amazonaws.com/"
        if raw.startswith(prefix):
            return _peel_key(raw[len(prefix) :])
    return None


def resolve_stored_url(stored: str | None) -> str | None:
    """Turn a DB/graph ref into a browser-fetchable URL (ADR 0025)."""
    if stored is None:
        return None
    raw = stored.strip()
    if not raw:
        return None
    if raw.startswith("placeholder://") or raw.startswith("data:"):
        return raw
    if raw.startswith(("http://", "https://", "/")):
        key = extract_store_key(raw)
        if key is not None:
            return public_url(key)
        return raw
    try:
        return public_url(raw)
    except MediaStorageError:
        return raw


def is_stored_image_ref(stored: str | None) -> bool:
    """True when Confirm should treat the ref as an image (not copy-only)."""
    raw = (stored or "").strip()
    if not raw or raw.startswith("placeholder://"):
        return False
    if raw.startswith(("http://", "https://", "data:image/")):
        return True
    try:
        normalize_key(raw)
        return True
    except MediaStorageError:
        return False


async def persist_generated_image(image_ref: str, *, key: str) -> str:
    """Persist a provider image result.

    - ``https://`` / ``http://`` — returned as-is (provider-hosted).
    - ``data:`` — uploaded; returns the object **key** (ADR 0025).
    - anything else — rejected (do not persist unknown schemes into
      ``preview_images.url``).
    """
    if image_ref.startswith("http://") or image_ref.startswith("https://"):
        return image_ref
    if image_ref.startswith("data:"):
        raw, content_type = parse_data_url(image_ref)
        content_type, key = _sniff_image_type(raw, content_type, key)
        await put_bytes(key=key, data=raw, content_type=content_type)
        return key
    snippet = image_ref[:32] if image_ref else ""
    raise MediaStorageError(f"Unsupported image ref scheme: {snippet!r}")


def _sniff_image_type(raw: bytes, content_type: str, key: str) -> tuple[str, str]:
    """Correct content type / extension when magic bytes disagree with the label."""
    if raw.startswith(_JPEG_MAGIC) and content_type == "image/png":
        content_type = "image/jpeg"
        if key.endswith(".png"):
            key = key[:-4] + ".jpg"
        return content_type, key
    if raw.startswith(_PNG_MAGIC) and content_type in ("image/jpeg", "image/jpg"):
        content_type = "image/png"
        if key.endswith(".jpeg"):
            key = key[:-5] + ".png"
        elif key.endswith(".jpg"):
            key = key[:-4] + ".png"
    return content_type, key


def media_object_key(*, session_id: str, revision: int, ext: str = "png") -> str:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "session"
    return normalize_key(f"sessions/{safe}/r{revision}-{secrets.token_hex(4)}.{ext}")
