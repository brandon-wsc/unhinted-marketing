"""Media asset storage facade (ADR 0024).

Callers use ``put_bytes`` / ``persist_generated_image`` / ``media_object_key``.
The backend is local disk when ``DEPLOYMENT_MODE=onprem`` and AWS S3 when
``cloud``.
"""

from __future__ import annotations

import base64
import secrets

from internal.media.backends import (
    MediaStorageError,
    assert_media_store_ready,
    local_media_path,
    normalize_key,
    resolve_media_store,
)

__all__ = [
    "MediaStorageError",
    "assert_media_store_ready",
    "local_media_path",
    "media_object_key",
    "parse_data_url",
    "persist_generated_image",
    "put_bytes",
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
    try:
        raw = base64.b64decode(payload, validate=False)
    except Exception as exc:
        raise MediaStorageError("Invalid base64 in data: URL") from exc
    return raw, content_type


async def put_bytes(*, key: str, data: bytes, content_type: str) -> str:
    """Upload bytes via the resolved store; return a browser-fetchable URL."""
    return await resolve_media_store().put_bytes(
        key=key, data=data, content_type=content_type
    )


async def persist_generated_image(image_ref: str, *, key: str) -> str:
    """Persist a provider image result.

    - ``https://`` / ``http://`` — returned as-is (provider-hosted).
    - ``data:`` — always uploaded to the resolved store.
    - anything else — rejected (do not persist unknown schemes into
      ``preview_images.url``).
    """
    if image_ref.startswith("http://") or image_ref.startswith("https://"):
        return image_ref
    if image_ref.startswith("data:"):
        raw, content_type = parse_data_url(image_ref)
        # Sniff JPEG mislabelled as png
        if raw.startswith(b"\xff\xd8\xff") and content_type == "image/png":
            content_type = "image/jpeg"
            if key.endswith(".png"):
                key = key[:-4] + ".jpg"
        return await put_bytes(key=key, data=raw, content_type=content_type)
    snippet = image_ref[:32] if image_ref else ""
    raise MediaStorageError(f"Unsupported image ref scheme: {snippet!r}")


def media_object_key(*, session_id: str, revision: int, ext: str = "png") -> str:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "session"
    return normalize_key(f"sessions/{safe}/r{revision}-{secrets.token_hex(4)}.{ext}")
