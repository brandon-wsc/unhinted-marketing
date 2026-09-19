"""Media storage (ADR 0024 + 0025) — local disk + S3 driver via snapshot, not env."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from internal.instance.config import reset_snapshot_cache as reset_instance_cache
from internal.media import storage as S
from internal.media.config import StorageSnapshot, publish_snapshot, reset_snapshot_cache

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xd9"
)

KEY = "sessions/abc/r1-deadbeef.png"
S3_ENDPOINT = "https://s3.example.test"
S3_PUBLIC = "https://cdn.example.test/media"


@pytest.fixture(autouse=True)
def local_media(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "media"
    monkeypatch.setattr(S.settings, "deployment_mode", "onprem")
    monkeypatch.setattr(S.settings, "s3_endpoint_url", None)
    monkeypatch.setattr(S.settings, "s3_bucket", None)
    monkeypatch.setattr(S.settings, "s3_access_key", None)
    monkeypatch.setattr(S.settings, "s3_secret_key", None)
    monkeypatch.setattr(S.settings, "s3_public_base_url", None)
    monkeypatch.setattr(S.settings, "s3_region", "us-east-1")
    monkeypatch.setattr(S.settings, "media_root", str(root))
    monkeypatch.setattr(S.settings, "web_base_url", "https://example.test")
    reset_snapshot_cache()
    reset_instance_cache()
    return root


def _s3_snap(**kwargs) -> StorageSnapshot:
    defaults = dict(
        backend="s3",
        bucket="unhinted-media",
        endpoint_url=S3_ENDPOINT,
        region="us-east-1",
        public_base_url=S3_PUBLIC,
        access_key="ak",
        secret_key="sk",
    )
    defaults.update(kwargs)
    return StorageSnapshot(**defaults)


def test_onprem_defaults_to_local() -> None:
    assert S.media_backend() == "local"


def test_parse_data_url_png() -> None:
    b64 = base64.b64encode(TINY_PNG).decode()
    data_url = f"data:image/png;base64,{b64}"
    raw, content_type = S.parse_data_url(data_url)
    assert raw == TINY_PNG
    assert content_type == "image/png"


def test_parse_data_url_rejects_non_data() -> None:
    with pytest.raises(S.MediaStorageError):
        S.parse_data_url("https://cdn.example/a.png")


def test_public_url_local() -> None:
    """Browser URLs stay relative so they follow the SPA origin (ADR 0024 2026-09-18)."""
    assert S.public_url(KEY) == f"/api/media/{KEY}"


def test_public_url_local_ignores_web_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(S.settings, "web_base_url", "https://example.test")
    reset_instance_cache()
    assert S.public_url(KEY) == f"/api/media/{KEY}"


def test_external_url_local_prefixes_web_base() -> None:
    assert S.external_url(KEY) == f"https://example.test/api/media/{KEY}"


def test_external_url_relative_when_web_base_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(S.settings, "web_base_url", "")
    reset_instance_cache()
    assert S.external_url(KEY) == f"/api/media/{KEY}"


def test_public_url_s3_uses_snapshot() -> None:
    publish_snapshot(_s3_snap())
    assert S.public_object_url(KEY) == f"{S3_PUBLIC}/{KEY}"


def test_s3_path_style_when_public_base_empty() -> None:
    publish_snapshot(_s3_snap(public_base_url=""))
    assert S.public_url(KEY) == f"{S3_ENDPOINT}/unhinted-media/{KEY}"


def test_cloud_virtual_host_when_no_endpoint() -> None:
    publish_snapshot(
        _s3_snap(endpoint_url="", public_base_url="", region="ap-east-1", bucket="prod-media")
    )
    assert S.public_url(KEY) == f"https://prod-media.s3.ap-east-1.amazonaws.com/{KEY}"


def test_extract_and_resolve_store_key() -> None:
    assert S.extract_store_key(KEY) == KEY
    assert S.resolve_stored_url(KEY) == f"/api/media/{KEY}"
    assert S.resolve_external_url(KEY) == f"https://example.test/api/media/{KEY}"


def test_extract_legacy_api_media_url() -> None:
    baked = f"https://old.example/api/media/{KEY}"
    assert S.extract_store_key(baked) == KEY
    assert S.extract_store_key(f"/api/media/{KEY}") == KEY
    assert S.resolve_stored_url(baked) == f"/api/media/{KEY}"
    assert S.resolve_external_url(baked) == f"https://example.test/api/media/{KEY}"


def test_extract_legacy_s3_bases() -> None:
    publish_snapshot(_s3_snap())
    assert S.extract_store_key(f"{S3_PUBLIC}/{KEY}") == KEY
    virtual = f"https://unhinted-media.s3.us-east-1.amazonaws.com/{KEY}"
    assert S.extract_store_key(virtual) == KEY


def test_extract_skips_provider_placeholder_data() -> None:
    assert S.extract_store_key("https://cdn.example/a.png") is None
    assert S.extract_store_key("placeholder://local/x.png") is None
    assert S.extract_store_key("data:image/png;base64,xx") is None
    assert S.resolve_stored_url("https://cdn.example/a.png") == "https://cdn.example/a.png"
    assert S.resolve_stored_url("placeholder://x") == "placeholder://x"


def test_stored_ref_is_image() -> None:
    assert S.stored_ref_is_image(KEY) is True
    assert S.stored_ref_is_image("https://cdn.example/a.png") is True
    assert S.stored_ref_is_image("data:image/png;base64,xx") is True
    assert S.stored_ref_is_image("placeholder://seed") is False
    assert S.stored_ref_is_image(None) is False
    assert S.stored_ref_is_image("") is False


def test_media_object_key_includes_hex() -> None:
    key = S.media_object_key(session_id="s1", revision=3, ext="png")
    assert key.startswith("sessions/s1/r3-")
    assert key.endswith(".png")
    assert S.is_store_key(key)


def test_local_path_rejects_traversal() -> None:
    with pytest.raises(S.MediaStorageError):
        S.local_abs_path("../secret.png")
    with pytest.raises(S.MediaStorageError):
        S.local_abs_path("sessions/../../etc/passwd")


@pytest.mark.asyncio
async def test_put_bytes_local_and_delete(local_media: Path) -> None:
    url = await S.put_bytes(key=KEY, data=TINY_PNG, content_type="image/png")
    assert url == f"/api/media/{KEY}"
    path = local_media / KEY
    assert path.read_bytes() == TINY_PNG
    await S.delete_key(KEY)
    assert not path.exists()
    assert not (local_media / "sessions" / "abc").exists()
    assert local_media.exists()


@pytest.mark.asyncio
async def test_put_bytes_s3_uploads(monkeypatch: pytest.MonkeyPatch) -> None:
    put_calls: list[dict] = []

    class FakeClient:
        def put_object(self, **kwargs):
            put_calls.append(kwargs)

    class FakeSession:
        def client(self, *args, **kwargs):
            assert kwargs.get("endpoint_url") == S3_ENDPOINT
            assert kwargs.get("config").s3["addressing_style"] == "path"
            return FakeClient()

    monkeypatch.setattr(S, "_boto3_session", lambda: FakeSession())
    publish_snapshot(_s3_snap())

    url = await S.put_bytes(key=KEY, data=TINY_PNG, content_type="image/png")
    assert url == f"{S3_PUBLIC}/{KEY}"
    assert put_calls[0]["Bucket"] == "unhinted-media"
    assert put_calls[0]["Key"] == KEY
    assert put_calls[0]["Body"] == TINY_PNG


@pytest.mark.asyncio
async def test_s3_delete_treats_missing_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from botocore.exceptions import ClientError

    class FakeClient:
        def delete_object(self, **kwargs):
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "DeleteObject",
            )

    class FakeSession:
        def client(self, *args, **kwargs):
            return FakeClient()

    monkeypatch.setattr(S, "_boto3_session", lambda: FakeSession())
    publish_snapshot(_s3_snap())
    await S.delete_key(KEY)


@pytest.mark.asyncio
async def test_persist_generated_image_data_url_returns_key(
    local_media: Path,
) -> None:
    b64 = base64.b64encode(TINY_PNG).decode()
    out = await S.persist_generated_image(
        f"data:image/png;base64,{b64}",
        key=KEY,
    )
    assert out == KEY
    assert (local_media / KEY).read_bytes() == TINY_PNG


@pytest.mark.asyncio
async def test_persist_generated_image_sniffs_jpeg_mislabeled_png(
    local_media: Path,
) -> None:
    b64 = base64.b64encode(TINY_JPEG).decode()
    out = await S.persist_generated_image(
        f"data:image/png;base64,{b64}",
        key="sessions/s1/r1-aaaa.png",
    )
    assert out.endswith(".jpg")
    assert (local_media / out).read_bytes() == TINY_JPEG


@pytest.mark.asyncio
async def test_persist_generated_image_passes_through_https() -> None:
    out = await S.persist_generated_image(
        "https://cdn.example/already.png",
        key=KEY,
    )
    assert out == "https://cdn.example/already.png"


@pytest.mark.asyncio
async def test_persist_generated_image_rejects_unknown_scheme() -> None:
    with pytest.raises(S.MediaStorageError, match="scheme"):
        await S.persist_generated_image("blob:local", key=KEY)


def test_sniff_image_bytes() -> None:
    assert S.sniff_image_bytes(TINY_PNG) == ("image/png", "png")
    assert S.sniff_image_bytes(TINY_JPEG) == ("image/jpeg", "jpg")
    assert S.sniff_image_bytes(b"not-an-image") is None


def test_sniff_image_bytes_gif_webp() -> None:
    assert S.sniff_image_bytes(b"GIF87a" + b"\x00" * 8) == ("image/gif", "gif")
    assert S.sniff_image_bytes(b"GIF89a" + b"\x00" * 8) == ("image/gif", "gif")
    webp = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 4
    assert S.sniff_image_bytes(webp) == ("image/webp", "webp")
    assert S.sniff_image_bytes(b"RIFF" + b"\x00" * 4 + b"AVI ") is None


def test_media_object_key_unique_per_call() -> None:
    """r{revision}-{hex}: concurrent regen/upload never overwrites the same bytes."""
    first = S.media_object_key(session_id="s1", revision=3, ext="png")
    second = S.media_object_key(session_id="s1", revision=3, ext="png")
    assert first != second


def test_extract_store_key_rejects_non_key_under_media_prefix() -> None:
    """A /api/media/ URL whose tail is not a store key is a provider ref, not ours."""
    assert S.extract_store_key("/api/media/not-a-key.png") is None
    assert S.extract_store_key("https://cdn.example/api/media/not-a-key.png") is None
    assert S.extract_store_key("/api/media/../etc/passwd") is None


def test_resolve_re_derives_after_web_base_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing WEB_BASE_URL applies to Confirm/Graph URLs; browser path is stable."""
    stored = KEY
    assert S.resolve_stored_url(stored) == f"/api/media/{KEY}"
    assert S.resolve_external_url(stored) == f"https://example.test/api/media/{KEY}"
    monkeypatch.setattr(S.settings, "web_base_url", "https://new.example")
    reset_instance_cache()
    assert S.resolve_stored_url(stored) == f"/api/media/{KEY}"
    assert S.resolve_external_url(stored) == f"https://new.example/api/media/{KEY}"
