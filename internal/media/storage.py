"""Media storage: local default on-prem; optional S3-compatible; AWS S3 in cloud (ADR 0024)."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

from internal.config import settings

logger = logging.getLogger(__name__)

# sessions/{id}/r{revision}-{hex}.{ext} (hex optional for leftover rN.ext keys)
_STORE_KEY_RE = re.compile(
    r"^sessions/[A-Za-z0-9_-]+/r\d+(?:-[0-9a-f]+)?\.[A-Za-z0-9]+$"
)
_API_MEDIA_PREFIX = "/api/media/"

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_GIF87 = b"GIF87a"
_GIF89 = b"GIF89a"


class MediaStorageError(Exception):
    """Misconfiguration or upload failure for media storage."""


def _strip(value: str | None) -> str:
    return (value or "").strip()


def media_backend() -> Literal["local", "s3"]:
    """Derive the store from DEPLOYMENT_MODE + S3 env (no STORAGE_BACKEND flag)."""
    mode = settings.deployment_mode
    bucket = _strip(settings.s3_bucket)
    endpoint = _strip(settings.s3_endpoint_url)
    access = _strip(settings.s3_access_key)
    secret = _strip(settings.s3_secret_key)

    if bool(access) != bool(secret):
        raise MediaStorageError(
            "S3_ACCESS_KEY and S3_SECRET_KEY must both be set, or both omitted "
            "(instance role / default boto3 chain)."
        )

    if mode == "cloud":
        if not bucket:
            raise MediaStorageError("S3_BUCKET is required when DEPLOYMENT_MODE=cloud.")
        return "s3"

    if bucket and endpoint:
        return "s3"
    if bucket or endpoint:
        raise MediaStorageError(
            "On-prem S3-compatible storage requires both S3_BUCKET and "
            "S3_ENDPOINT_URL (or neither, to use local disk)."
        )
    return "local"


def assert_media_storage_config() -> None:
    """Refuse incomplete S3 env at process start (ADR 0024)."""
    try:
        media_backend()
    except MediaStorageError as exc:
        raise RuntimeError(str(exc)) from exc


def media_storage_configured() -> bool:
    """True when the S3 driver is selected (live S3 tests)."""
    try:
        return media_backend() == "s3"
    except MediaStorageError:
        return False


def sniff_image_bytes(data: bytes) -> tuple[str, str] | None:
    """Return ``(content_type, ext)`` from PNG/JPEG/WebP/GIF magic, or None."""
    if data.startswith(_PNG_MAGIC):
        return "image/png", "png"
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg", "jpg"
    if data.startswith(_GIF87) or data.startswith(_GIF89):
        return "image/gif", "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def is_store_key(value: str) -> bool:
    return bool(_STORE_KEY_RE.match(value))


def _safe_relative_key(key: str) -> bool:
    if not key or key.startswith("/") or "\\" in key:
        return False
    parts = key.split("/")
    return bool(parts) and all(p not in ("", ".", "..") for p in parts)


def local_abs_path(key: str) -> Path:
    """Resolve ``key`` under MEDIA_ROOT; reject path traversal."""
    if not _safe_relative_key(key):
        raise MediaStorageError("Invalid media key")
    root = Path(settings.media_root).expanduser().resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise MediaStorageError("Invalid media key")
    return path


def public_url(key: str) -> str:
    """Browser-fetchable URL for an object key (not stored in Postgres)."""
    key = key.lstrip("/")
    if media_backend() == "local":
        base = _strip(settings.web_base_url).rstrip("/")
        path = f"{_API_MEDIA_PREFIX}{key}"
        return f"{base}{path}" if base else path
    pub = _strip(settings.s3_public_base_url).rstrip("/")
    if pub:
        return f"{pub}/{key}"
    endpoint = _strip(settings.s3_endpoint_url).rstrip("/")
    bucket = _strip(settings.s3_bucket)
    if endpoint:
        return f"{endpoint}/{bucket}/{key}"
    region = _strip(settings.s3_region) or "us-east-1"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


def public_object_url(key: str) -> str:
    return public_url(key)


def _s3_peel_prefixes() -> list[str]:
    prefixes: list[str] = []
    pub = _strip(settings.s3_public_base_url).rstrip("/")
    if pub:
        prefixes.append(pub + "/")
    endpoint = _strip(settings.s3_endpoint_url).rstrip("/")
    bucket = _strip(settings.s3_bucket)
    if endpoint and bucket:
        prefixes.append(f"{endpoint}/{bucket}/")
    region = _strip(settings.s3_region) or "us-east-1"
    if bucket:
        prefixes.append(f"https://{bucket}.s3.{region}.amazonaws.com/")
    return prefixes


def extract_store_key(stored: str | None) -> str | None:
    """Peel an object key from a stored ref; None for provider / placeholder / data."""
    if stored is None:
        return None
    value = stored.strip()
    if not value:
        return None
    if value.startswith("placeholder://") or value.startswith("data:"):
        return None
    if is_store_key(value):
        return value
    if value.startswith(_API_MEDIA_PREFIX):
        key = value[len(_API_MEDIA_PREFIX) :].lstrip("/")
        return key if is_store_key(key) else None
    if value.startswith("http://") or value.startswith("https://"):
        idx = value.find(_API_MEDIA_PREFIX)
        if idx >= 0:
            key = value[idx + len(_API_MEDIA_PREFIX) :].lstrip("/")
            return key if is_store_key(key) else None
        for prefix in _s3_peel_prefixes():
            if value.startswith(prefix):
                key = value[len(prefix) :].lstrip("/")
                return key if is_store_key(key) else None
    return None


def resolve_stored_url(stored: str | None) -> str | None:
    """Read choke point: object key / leftover baked URL → current public URL."""
    if stored is None:
        return None
    value = stored.strip()
    if not value:
        return None
    key = extract_store_key(value)
    if key:
        return public_url(key)
    return value


def stored_ref_is_image(stored: str | None) -> bool:
    """Confirm copy-only gate: http(s) / data:image / valid key count; placeholder does not."""
    if stored is None:
        return False
    value = stored.strip()
    if not value or value.startswith("placeholder://"):
        return False
    if value.startswith("http://") or value.startswith("https://"):
        return True
    if value.startswith("data:image/"):
        return True
    return extract_store_key(value) is not None


def parse_data_url(data_url: str) -> tuple[bytes, str]:
    if not data_url.startswith("data:"):
        raise MediaStorageError("Expected a data: URL")
    header, _, payload = data_url.partition(",")
    if not payload:
        raise MediaStorageError("Malformed data: URL (missing payload)")
    meta = header[5:]
    content_type = meta.split(";", 1)[0] or "application/octet-stream"
    if ";base64" not in meta:
        raise MediaStorageError("Only base64 data: URLs are supported")
    try:
        raw = base64.b64decode(payload, validate=False)
    except Exception as exc:
        raise MediaStorageError("Invalid base64 in data: URL") from exc
    return raw, content_type


@lru_cache(maxsize=1)
def _boto3_session():
    return boto3.session.Session()


def _s3_client() -> BaseClient:
    if media_backend() != "s3":
        raise MediaStorageError("S3 media storage is not selected.")
    endpoint = _strip(settings.s3_endpoint_url) or None
    access = _strip(settings.s3_access_key)
    secret = _strip(settings.s3_secret_key)
    kwargs: dict = {"region_name": _strip(settings.s3_region) or "us-east-1"}
    if endpoint:
        kwargs["endpoint_url"] = endpoint
        kwargs["config"] = Config(s3={"addressing_style": "path"})
    if access and secret:
        kwargs["aws_access_key_id"] = access
        kwargs["aws_secret_access_key"] = secret
    return _boto3_session().client("s3", **kwargs)


def _prune_empty_parents(start: Path, root: Path) -> None:
    current = start
    while current != root and current.is_relative_to(root):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _put_bytes_sync(*, key: str, data: bytes, content_type: str) -> str:
    if media_backend() == "local":
        path = local_abs_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return public_url(key)
    client = _s3_client()
    client.put_object(
        Bucket=_strip(settings.s3_bucket),
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return public_url(key)


def _delete_key_sync(key: str) -> None:
    if media_backend() == "local":
        path = local_abs_path(key)
        path.unlink(missing_ok=True)
        _prune_empty_parents(path.parent, Path(settings.media_root).expanduser().resolve())
        return
    client = _s3_client()
    try:
        client.delete_object(Bucket=_strip(settings.s3_bucket), Key=key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {"NotFound", "NoSuchKey", "404"}:
            raise MediaStorageError(f"delete_object failed: {exc}") from exc


async def put_bytes(*, key: str, data: bytes, content_type: str) -> str:
    """Write bytes; return a browser-fetchable URL (Postgres stores the key, not this)."""
    return await asyncio.to_thread(
        _put_bytes_sync, key=key, data=data, content_type=content_type
    )


async def delete_key(key: str) -> None:
    """Idempotent object delete (local unlink or S3 delete_object)."""
    await asyncio.to_thread(_delete_key_sync, key)


def _replace_key_ext(key: str, ext: str) -> str:
    stem, dot, _old = key.rpartition(".")
    if stem and dot:
        return f"{stem}.{ext}"
    return key


async def persist_generated_image(image_ref: str, *, key: str) -> str:
    """Persist a provider image result.

    - ``https://`` / ``http://`` — returned as-is (provider-hosted).
    - ``data:`` — always written; returns the object key.
    - anything else — rejected.
    """
    if image_ref.startswith("http://") or image_ref.startswith("https://"):
        return image_ref
    if image_ref.startswith("data:"):
        raw, content_type = parse_data_url(image_ref)
        sniffed = sniff_image_bytes(raw)
        if sniffed:
            content_type, ext = sniffed
            key = _replace_key_ext(key, ext)
        await put_bytes(key=key, data=raw, content_type=content_type)
        return key
    raise MediaStorageError(
        "Unsupported image scheme (expected http(s) or data:)."
    )


def media_object_key(*, session_id: str, revision: int, ext: str = "png") -> str:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "session"
    token = secrets.token_hex(4)
    return f"sessions/{safe}/r{revision}-{token}.{ext}"
