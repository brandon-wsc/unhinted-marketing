"""Media storage: local default on-prem; optional S3-compatible; AWS S3 in cloud (ADR 0024 + 0025)."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

from internal.config import settings
from internal.media.config import StorageSnapshot, get_snapshot

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
    """Active store from the published snapshot (DB) or env seed fallback (ADR 0025)."""
    try:
        return get_snapshot().backend
    except RuntimeError as exc:
        raise MediaStorageError(str(exc)) from exc


def dual_write_active() -> bool:
    try:
        return get_snapshot().dual_write
    except RuntimeError:
        return False


def local_read_grace() -> bool:
    """Serve leftover local files after flip, until cleanup (ADR 0025)."""
    try:
        snap = get_snapshot()
    except RuntimeError:
        return False
    return snap.backend == "s3" and snap.dual_write


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


def public_url_for(key: str, snap: StorageSnapshot) -> str:
    """Browser-fetchable URL for an object key under ``snap``.

    Local is always a same-origin path so ``<img>`` follows the SPA origin
    (Vite may hop ports; baking ``WEB_BASE_URL`` 404s). S3 stays absolute.
    """
    key = key.lstrip("/")
    if snap.backend == "local":
        return f"{_API_MEDIA_PREFIX}{key}"
    pub = _strip(snap.public_base_url).rstrip("/")
    if pub:
        return f"{pub}/{key}"
    endpoint = _strip(snap.endpoint_url).rstrip("/")
    bucket = _strip(snap.bucket)
    if endpoint:
        return f"{endpoint}/{bucket}/{key}"
    region = _strip(snap.region) or "us-east-1"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


def _local_web_base() -> str:
    from internal.instance.config import get_snapshot as get_instance_snapshot

    return _strip(get_instance_snapshot().web_base_url).rstrip("/")


def external_url_for(key: str, snap: StorageSnapshot) -> str:
    """Meta-reachable URL: local prefixes ``WEB_BASE_URL``; S3 uses ``public_url``."""
    url = public_url_for(key, snap)
    if url.startswith("/") and not url.startswith("//"):
        base = _local_web_base()
        return f"{base}{url}" if base else url
    return url


def public_url(key: str) -> str:
    """Browser-fetchable URL for an object key (not stored in Postgres)."""
    return public_url_for(key, get_snapshot())


def external_url(key: str) -> str:
    """Absolute URL for off-browser fetchers (Instagram Graph ``image_url``)."""
    return external_url_for(key, get_snapshot())


def public_object_url(key: str) -> str:
    return public_url(key)


def _s3_peel_prefixes() -> list[str]:
    """Peel keys from URLs under the *active* snapshot bases (not leftover env)."""
    prefixes: list[str] = []
    try:
        snap = get_snapshot()
    except RuntimeError:
        return prefixes
    pub = _strip(snap.public_base_url).rstrip("/")
    if pub:
        prefixes.append(pub + "/")
    endpoint = _strip(snap.endpoint_url).rstrip("/")
    bucket = _strip(snap.bucket)
    if endpoint and bucket:
        prefixes.append(f"{endpoint}/{bucket}/")
    region = _strip(snap.region) or "us-east-1"
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


def resolve_external_url(stored: str | None) -> str | None:
    """Like ``resolve_stored_url`` but absolute — Instagram Confirm / Graph fetch."""
    if stored is None:
        return None
    value = stored.strip()
    if not value:
        return None
    key = extract_store_key(value)
    if key:
        return external_url(key)
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


def s3_client_for(snap: StorageSnapshot) -> BaseClient:
    endpoint = _strip(snap.endpoint_url) or None
    access = _strip(snap.access_key)
    secret = _strip(snap.secret_key)
    kwargs: dict = {"region_name": _strip(snap.region) or "us-east-1"}
    if endpoint:
        kwargs["endpoint_url"] = endpoint
        kwargs["config"] = Config(s3={"addressing_style": "path"})
    if access and secret:
        kwargs["aws_access_key_id"] = access
        kwargs["aws_secret_access_key"] = secret
    return _boto3_session().client("s3", **kwargs)


def _s3_client() -> BaseClient:
    snap = get_snapshot()
    if snap.backend != "s3" and not snap.dual_write:
        raise MediaStorageError("S3 media storage is not selected.")
    if not _strip(snap.bucket):
        raise MediaStorageError("S3 bucket is not configured.")
    return s3_client_for(snap)


def _prune_empty_parents(start: Path, root: Path) -> None:
    current = start
    while current != root and current.is_relative_to(root):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _put_local_sync(*, key: str, data: bytes) -> None:
    path = local_abs_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _put_s3_sync(*, snap: StorageSnapshot, key: str, data: bytes, content_type: str) -> None:
    client = s3_client_for(snap)
    client.put_object(
        Bucket=_strip(snap.bucket),
        Key=key,
        Body=data,
        ContentType=content_type,
    )


def _head_s3_size_sync(*, snap: StorageSnapshot, key: str) -> int | None:
    client = s3_client_for(snap)
    try:
        resp = client.head_object(Bucket=_strip(snap.bucket), Key=key)
    except ClientError:
        return None
    length = resp.get("ContentLength")
    return int(length) if length is not None else None


def _delete_local_sync(key: str) -> None:
    path = local_abs_path(key)
    path.unlink(missing_ok=True)
    _prune_empty_parents(path.parent, Path(settings.media_root).expanduser().resolve())


def _delete_s3_sync(*, snap: StorageSnapshot, key: str) -> None:
    client = s3_client_for(snap)
    try:
        client.delete_object(Bucket=_strip(snap.bucket), Key=key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {"NotFound", "NoSuchKey", "404"}:
            raise MediaStorageError(f"delete_object failed: {exc}") from exc


@dataclass
class _PutOutcome:
    url: str
    dual_s3_copied: bool = False


def _put_bytes_sync(*, key: str, data: bytes, content_type: str) -> _PutOutcome:
    snap = get_snapshot()
    write_local = snap.backend == "local" or snap.dual_write
    write_s3 = snap.backend == "s3" or snap.dual_write
    dual_s3_copied = False

    if snap.backend == "local" and write_local:
        _put_local_sync(key=key, data=data)
        target = snap.dual_s3()
        if write_s3 and _strip(target.bucket):
            try:
                _put_s3_sync(snap=target, key=key, data=data, content_type=content_type)
                dual_s3_copied = True
            except Exception:
                logger.warning("dual-write S3 put failed for key=%s", key, exc_info=True)
        return _PutOutcome(url=public_url_for(key, snap), dual_s3_copied=dual_s3_copied)

    if not write_s3:
        raise MediaStorageError("S3 media storage is not selected.")
    _put_s3_sync(snap=snap, key=key, data=data, content_type=content_type)
    dual_s3_copied = True
    if write_local:
        try:
            _put_local_sync(key=key, data=data)
        except Exception:
            logger.warning("dual-write local put failed for key=%s", key, exc_info=True)
    return _PutOutcome(url=public_url_for(key, snap), dual_s3_copied=dual_s3_copied)


def _delete_key_sync(key: str) -> None:
    snap = get_snapshot()
    write_local = snap.backend == "local" or snap.dual_write
    write_s3 = snap.backend == "s3" or snap.dual_write
    if write_local:
        _delete_local_sync(key)
    if write_s3:
        target = snap.dual_s3() if snap.backend == "local" else snap
        if _strip(target.bucket):
            _delete_s3_sync(snap=target, key=key)


async def put_bytes(*, key: str, data: bytes, content_type: str) -> str:
    """Write bytes; return a browser-fetchable URL (Postgres stores the key, not this)."""
    outcome = await asyncio.to_thread(
        _put_bytes_sync, key=key, data=data, content_type=content_type
    )
    if outcome.dual_s3_copied and get_snapshot().dual_write:
        try:
            from internal.memory.database import open_session
            from internal.memory.repos import mark_migration_key_done

            async with open_session() as db:
                await mark_migration_key_done(db, key, len(data))
                await db.commit()
        except Exception:
            logger.warning("migration_done_keys insert failed for key=%s", key, exc_info=True)
    return outcome.url


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
