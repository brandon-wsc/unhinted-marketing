"""Optional live MinIO check — skipped unless S3_ENDPOINT_URL is reachable.

Run after: docker compose up -d minio minio-init
  S3_ENDPOINT_URL=http://127.0.0.1:9000 \\
  S3_ACCESS_KEY=minioadmin S3_SECRET_KEY=minioadmin \\
  S3_BUCKET=unhinted-media \\
  pytest tests/unit/test_media_storage_live.py -m minio -q
"""

from __future__ import annotations

import base64
import socket
import uuid
from urllib.parse import urlparse

import pytest

from internal.config import settings
from internal.media import storage as S

pytestmark = pytest.mark.minio

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _endpoint_reachable() -> bool:
    raw = (settings.s3_endpoint_url or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def _require_minio() -> None:
    if not S.media_storage_configured() or not _endpoint_reachable():
        pytest.skip("MinIO not configured/reachable — start docker compose minio first")


@pytest.mark.asyncio
async def test_live_put_and_fetch_roundtrip() -> None:
    key = f"tests/{uuid.uuid4().hex}.png"
    url = await S.put_bytes(key=key, data=TINY_PNG, content_type="image/png")
    assert url.startswith("http")
    assert key in url

    import urllib.request

    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 — local MinIO
        body = resp.read()
    assert body == TINY_PNG
