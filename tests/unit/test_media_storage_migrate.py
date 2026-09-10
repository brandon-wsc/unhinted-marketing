"""Storage snapshot + dual-write (ADR 0025) — no DB required."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from internal.media import storage as S
from internal.media.config import StorageSnapshot, publish_snapshot, reset_snapshot_cache
from internal.media.migrate import count_orphan_files, enumerate_store_keys

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
KEY = "sessions/abc/r1-deadbeef.png"


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs):
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def head_object(self, **kwargs):
        body = self.objects.get(kwargs["Key"])
        if body is None:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "missing"}},
                "HeadObject",
            )
        return {"ContentLength": len(body)}

    def delete_object(self, **kwargs):
        self.objects.pop(kwargs["Key"], None)


@pytest.fixture(autouse=True)
def no_real_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dual-write put_bytes must not open DATABASE_URL from unit tests."""

    class _NoDb:
        async def __aenter__(self):
            raise RuntimeError("unit test: no DB")

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("internal.memory.database.open_session", lambda: _NoDb())


@pytest.fixture(autouse=True)
def local_media(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "media"
    monkeypatch.setattr(S.settings, "deployment_mode", "onprem")
    monkeypatch.setattr(S.settings, "s3_endpoint_url", None)
    monkeypatch.setattr(S.settings, "s3_bucket", None)
    monkeypatch.setattr(S.settings, "s3_access_key", None)
    monkeypatch.setattr(S.settings, "s3_secret_key", None)
    monkeypatch.setattr(S.settings, "s3_public_base_url", None)
    monkeypatch.setattr(S.settings, "media_root", str(root))
    monkeypatch.setattr(S.settings, "web_base_url", "https://example.test")
    reset_snapshot_cache()
    return root


def _dual_snap() -> StorageSnapshot:
    return StorageSnapshot(
        backend="local",
        dual_write=True,
        dual_bucket="unhinted-media",
        dual_endpoint_url="http://127.0.0.1:9000",
        dual_region="us-east-1",
        dual_access_key="garage",
        dual_secret_key="garage",
    )


@pytest.mark.asyncio
async def test_dual_write_puts_local_and_s3(
    local_media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeS3()

    class FakeSession:
        def client(self, *args, **kwargs):
            return fake

    monkeypatch.setattr(S, "_boto3_session", lambda: FakeSession())
    publish_snapshot(_dual_snap())

    url = await S.put_bytes(key=KEY, data=TINY_PNG, content_type="image/png")
    assert url == f"https://example.test/api/media/{KEY}"
    assert (local_media / KEY).read_bytes() == TINY_PNG
    assert fake.objects[KEY] == TINY_PNG


@pytest.mark.asyncio
async def test_dual_write_s3_failure_still_serves_local(
    local_media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Boom:
        def put_object(self, **kwargs):
            raise RuntimeError("s3 down")

    class FakeSession:
        def client(self, *args, **kwargs):
            return Boom()

    monkeypatch.setattr(S, "_boto3_session", lambda: FakeSession())
    publish_snapshot(_dual_snap())

    url = await S.put_bytes(key=KEY, data=TINY_PNG, content_type="image/png")
    assert url.endswith(KEY)
    assert (local_media / KEY).read_bytes() == TINY_PNG


@pytest.mark.asyncio
async def test_dual_delete_hits_both(
    local_media: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeS3()
    fake.objects[KEY] = TINY_PNG
    path = local_media / KEY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(TINY_PNG)

    class FakeSession:
        def client(self, *args, **kwargs):
            return fake

    monkeypatch.setattr(S, "_boto3_session", lambda: FakeSession())
    publish_snapshot(_dual_snap())
    await S.delete_key(KEY)
    assert not path.exists()
    assert KEY not in fake.objects


def test_local_read_grace_after_s3_flip() -> None:
    publish_snapshot(
        StorageSnapshot(backend="s3", bucket="b", dual_write=True, dual_bucket="b")
    )
    assert S.media_backend() == "s3"
    assert S.local_read_grace() is True
    publish_snapshot(StorageSnapshot(backend="s3", bucket="b", dual_write=False))
    assert S.local_read_grace() is False


def test_enumerate_store_keys_peels_mixed_refs() -> None:
    keys = enumerate_store_keys(
        [
            KEY,
            f"/api/media/{KEY}",
            "https://cdn.example/a.png",
            "placeholder://x",
            "data:image/png;base64,xx",
            None,  # type: ignore[list-item]
        ]
    )
    assert keys == [KEY]


def test_count_orphan_files(local_media: Path) -> None:
    known = local_media / KEY
    known.parent.mkdir(parents=True)
    known.write_bytes(TINY_PNG)
    orphan = local_media / "sessions" / "abc" / "leftover.png"
    orphan.write_bytes(TINY_PNG)
    assert count_orphan_files({KEY}) == 1
