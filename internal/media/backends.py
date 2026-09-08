"""Media store backends — local disk (on-prem) or AWS S3 (cloud). ADR 0024."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from internal.config import settings


class MediaStorageError(Exception):
    """Misconfiguration or upload failure for media storage."""


def normalize_key(key: str) -> str:
    """Reject empty, absolute, or `..` keys; return a POSIX relative path."""
    raw = (key or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/"):
        raise MediaStorageError("Invalid media key")
    parts = tuple(p for p in raw.split("/") if p)
    if not parts or any(p in (".", "..") for p in parts):
        raise MediaStorageError("Invalid media key")
    return "/".join(parts)


class MediaStore(Protocol):
    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> str:
        """Store bytes and return a browser-fetchable URL."""

    def public_url(self, key: str) -> str:
        """Browser-facing URL for an already-stored key."""


class LocalStore:
    """On-prem filesystem store under MEDIA_ROOT."""

    def __init__(self, root: Path, public_base: str) -> None:
        self._root = root
        self._public_base = public_base.rstrip("/")

    def public_url(self, key: str) -> str:
        rel = quote(normalize_key(key), safe="/")
        return f"{self._public_base}/{rel}"

    def local_path(self, key: str) -> Path:
        rel = normalize_key(key)
        root = self._root.resolve()
        path = (root / rel).resolve()
        if not path.is_relative_to(root):
            raise MediaStorageError("Invalid media key")
        return path

    def _put_sync(self, *, key: str, data: bytes) -> str:
        path = self.local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.public_url(key)

    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> str:
        _ = content_type
        return await asyncio.to_thread(self._put_sync, key=key, data=data)


@lru_cache(maxsize=4)
def _s3_client_for(region: str, access: str, secret: str) -> BaseClient:
    kwargs: dict[str, str] = {"region_name": region}
    if access and secret:
        kwargs["aws_access_key_id"] = access
        kwargs["aws_secret_access_key"] = secret
    return boto3.session.Session().client("s3", **kwargs)


def _s3_client() -> BaseClient:
    return _s3_client_for(
        settings.s3_region or "us-east-1",
        (settings.s3_access_key or "").strip(),
        (settings.s3_secret_key or "").strip(),
    )


class S3Store:
    """Cloud AWS S3 (no custom endpoint)."""

    def public_url(self, key: str) -> str:
        rel = quote(normalize_key(key), safe="/")
        base = (settings.s3_public_base_url or "").strip().rstrip("/")
        if base:
            return f"{base}/{rel}"
        bucket = (settings.s3_bucket or "").strip()
        region = settings.s3_region or "us-east-1"
        return f"https://{bucket}.s3.{region}.amazonaws.com/{rel}"

    def _put_sync(self, *, key: str, data: bytes, content_type: str) -> str:
        rel = normalize_key(key)
        bucket = (settings.s3_bucket or "").strip()
        if not bucket:
            raise MediaStorageError("S3_BUCKET is not set")
        try:
            _s3_client().put_object(
                Bucket=bucket,
                Key=rel,
                Body=data,
                ContentType=content_type,
            )
        except ClientError as exc:
            raise MediaStorageError(f"S3 put_object failed: {exc}") from exc
        return self.public_url(rel)

    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> str:
        return await asyncio.to_thread(
            self._put_sync, key=key, data=data, content_type=content_type
        )


def _local_public_base() -> str:
    origin = (settings.web_base_url or "").strip().rstrip("/")
    if origin:
        return f"{origin}/api/media"
    return "/api/media"


def resolve_media_store() -> MediaStore:
    if settings.deployment_mode == "cloud":
        return S3Store()
    root = Path(settings.media_root or "data/media")
    return LocalStore(root=root, public_base=_local_public_base())


def assert_media_store_ready() -> None:
    """Fail at process start when media is misconfigured (ADR 0024)."""
    if settings.deployment_mode == "cloud":
        if not (settings.s3_bucket or "").strip():
            raise RuntimeError(
                "DEPLOYMENT_MODE=cloud requires S3_BUCKET. Set the AWS bucket name, "
                "or DEPLOYMENT_MODE=onprem to write media to local disk."
            )
        access = (settings.s3_access_key or "").strip()
        secret = (settings.s3_secret_key or "").strip()
        if bool(access) != bool(secret):
            raise RuntimeError(
                "S3_ACCESS_KEY and S3_SECRET_KEY must both be set, or both omitted "
                "to use the default AWS credential chain (instance role)."
            )
        return
    root = Path(settings.media_root or "data/media")
    try:
        root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir():
            raise RuntimeError(
                f"MEDIA_ROOT={root} exists but is not a directory."
            )
        probe = root / ".writable"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        raise RuntimeError(
            f"MEDIA_ROOT={root} is not writable. Create the directory or set "
            "MEDIA_ROOT to a writable path."
        ) from exc


def local_media_path(key: str) -> Path | None:
    """Filesystem path for GET /api/media, or None when the store is not local."""
    store = resolve_media_store()
    local_path = getattr(store, "local_path", None)
    if local_path is None:
        return None
    path = local_path(key)
    return path if path.is_file() else None
