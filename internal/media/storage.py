"""S3-compatible media storage (MinIO locally; R2/S3 in the cloud)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from functools import lru_cache

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from internal.config import settings

logger = logging.getLogger(__name__)


class MediaStorageError(Exception):
    """Misconfiguration or upload failure for media storage."""


def media_storage_configured() -> bool:
    return bool(
        (settings.s3_endpoint_url or "").strip()
        and (settings.s3_bucket or "").strip()
        and (settings.s3_access_key or "").strip()
        and (settings.s3_secret_key or "").strip()
    )


def public_object_url(key: str) -> str:
    base = (settings.s3_public_base_url or "").strip().rstrip("/")
    if not base:
        endpoint = (settings.s3_endpoint_url or "").rstrip("/")
        bucket = settings.s3_bucket or ""
        base = f"{endpoint}/{bucket}"
    return f"{base}/{key.lstrip('/')}"


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


@lru_cache(maxsize=1)
def _boto3_session():
    return boto3.session.Session()


def _s3_client() -> BaseClient:
    if not media_storage_configured():
        raise MediaStorageError(
            "S3 media storage is not configured "
            "(set S3_ENDPOINT_URL, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY)."
        )
    return _boto3_session().client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region or "us-east-1",
    )


def _public_read_policy(bucket: str) -> str:
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket}/*"],
                }
            ],
        }
    )


def _ensure_bucket_sync() -> None:
    client = _s3_client()
    bucket = settings.s3_bucket or ""
    try:
        client.head_bucket(Bucket=bucket)
        return
    except ClientError:
        pass
    try:
        client.create_bucket(Bucket=bucket)
        logger.info("Created media bucket %s", bucket)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            raise MediaStorageError(f"create_bucket failed: {exc}") from exc
    try:
        client.put_bucket_policy(Bucket=bucket, Policy=_public_read_policy(bucket))
    except ClientError as exc:
        logger.warning("Could not set public-read policy on %s: %s", bucket, exc)


async def ensure_bucket() -> None:
    """Create the media bucket (and public-read policy) if missing."""
    await asyncio.to_thread(_ensure_bucket_sync)


def _put_bytes_sync(*, key: str, data: bytes, content_type: str) -> str:
    client = _s3_client()
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return public_object_url(key)


async def put_bytes(*, key: str, data: bytes, content_type: str) -> str:
    """Upload bytes to the configured bucket; return a browser-fetchable URL."""
    if not media_storage_configured():
        raise MediaStorageError(
            "S3 media storage is not configured "
            "(set S3_ENDPOINT_URL, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY)."
        )
    return await asyncio.to_thread(
        _put_bytes_sync, key=key, data=data, content_type=content_type
    )


async def persist_generated_image(image_ref: str, *, key: str) -> str:
    """Persist a provider image result.

    - ``https://`` / ``http://`` — returned as-is (provider-hosted).
    - ``data:`` — uploaded when S3 is configured; otherwise left as data URL.
    """
    if image_ref.startswith("http://") or image_ref.startswith("https://"):
        return image_ref
    if image_ref.startswith("data:"):
        if not media_storage_configured():
            return image_ref
        raw, content_type = parse_data_url(image_ref)
        # Sniff JPEG mislabelled as png
        if raw.startswith(b"\xff\xd8\xff") and content_type == "image/png":
            content_type = "image/jpeg"
            if key.endswith(".png"):
                key = key[: -4] + ".jpg"
        await ensure_bucket()
        return await put_bytes(key=key, data=raw, content_type=content_type)
    return image_ref


def media_object_key(*, session_id: str, revision: int, ext: str = "png") -> str:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "session"
    return f"sessions/{safe}/r{revision}.{ext}"
