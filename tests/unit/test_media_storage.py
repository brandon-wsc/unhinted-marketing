"""Media storage (ADR 0024) — local disk default, optional S3, key resolve."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from internal.media import storage as S
from internal.media.config import reset_snapshot_cache

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xd9"
)

KEY = "sessions/abc/r1-deadbeef.png"


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
    return root


@pytest.fixture
def s3_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(S.settings, "deployment_mode", "onprem")
    monkeypatch.setattr(S.settings, "s3_endpoint_url", "http://127.0.0.1:9000")
    monkeypatch.setattr(S.settings, "s3_access_key", "garage")
    monkeypatch.setattr(S.settings, "s3_secret_key", "garage")
    monkeypatch.setattr(S.settings, "s3_bucket", "unhinted-media")
    monkeypatch.setattr(S.settings, "s3_region", "us-east-1")
    monkeypatch.setattr(
        S.settings, "s3_public_base_url", "http://127.0.0.1:9000/unhinted-media"
    )
    reset_snapshot_cache()


def test_onprem_defaults_to_local() -> None:
    assert S.media_backend() == "local"
    assert S.media_storage_configured() is False
    S.assert_media_storage_config()  # does not raise


def test_onprem_s3_when_bucket_and_endpoint(s3_settings: None) -> None:
    assert S.media_backend() == "s3"
    assert S.media_storage_configured() is True


def test_onprem_incomplete_s3_env_stays_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(S.settings, "s3_bucket", "unhinted-media")
    monkeypatch.setattr(S.settings, "s3_endpoint_url", None)
    reset_snapshot_cache()
    assert S.media_backend() == "local"
    S.assert_media_storage_config()


def test_single_s3_key_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(S.settings, "s3_access_key", "only-access")
    monkeypatch.setattr(S.settings, "s3_secret_key", None)
    reset_snapshot_cache()
    assert S.media_backend() == "local"


def test_cloud_requires_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(S.settings, "deployment_mode", "cloud")
    with pytest.raises(S.MediaStorageError, match="S3_BUCKET"):
        S.media_backend()


def test_cloud_without_endpoint_uses_virtual_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(S.settings, "deployment_mode", "cloud")
    monkeypatch.setattr(S.settings, "s3_bucket", "prod-media")
    monkeypatch.setattr(S.settings, "s3_region", "ap-east-1")
    assert S.media_backend() == "s3"
    assert (
        S.public_url(KEY)
        == f"https://prod-media.s3.ap-east-1.amazonaws.com/{KEY}"
    )


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
    assert S.public_url(KEY) == f"https://example.test/api/media/{KEY}"


def test_public_url_local_relative_when_web_base_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(S.settings, "web_base_url", "")
    assert S.public_url(KEY) == f"/api/media/{KEY}"


def test_public_object_url_s3(s3_settings: None) -> None:
    assert S.public_object_url(KEY) == f"http://127.0.0.1:9000/unhinted-media/{KEY}"


def test_s3_path_style_when_public_base_empty(
    s3_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(S.settings, "s3_public_base_url", None)
    assert S.public_url(KEY) == f"http://127.0.0.1:9000/unhinted-media/{KEY}"


def test_extract_and_resolve_store_key() -> None:
    assert S.extract_store_key(KEY) == KEY
    assert S.resolve_stored_url(KEY) == f"https://example.test/api/media/{KEY}"


def test_extract_legacy_api_media_url() -> None:
    baked = f"https://old.example/api/media/{KEY}"
    assert S.extract_store_key(baked) == KEY
    assert S.extract_store_key(f"/api/media/{KEY}") == KEY
    assert S.resolve_stored_url(baked) == f"https://example.test/api/media/{KEY}"


def test_extract_legacy_s3_bases(s3_settings: None) -> None:
    baked = f"http://127.0.0.1:9000/unhinted-media/{KEY}"
    assert S.extract_store_key(baked) == KEY
    monkeypatch_url = f"https://unhinted-media.s3.us-east-1.amazonaws.com/{KEY}"
    assert S.extract_store_key(monkeypatch_url) == KEY


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
    assert url == f"https://example.test/api/media/{KEY}"
    path = local_media / KEY
    assert path.read_bytes() == TINY_PNG
    await S.delete_key(KEY)
    assert not path.exists()
    # empty parents pruned up to MEDIA_ROOT
    assert not (local_media / "sessions" / "abc").exists()
    assert local_media.exists()


@pytest.mark.asyncio
async def test_put_bytes_s3_uploads(
    s3_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_calls: list[dict] = []

    class FakeClient:
        def put_object(self, **kwargs):
            put_calls.append(kwargs)

    class FakeSession:
        def client(self, *args, **kwargs):
            assert kwargs.get("endpoint_url") == "http://127.0.0.1:9000"
            assert kwargs.get("config").s3["addressing_style"] == "path"
            return FakeClient()

    monkeypatch.setattr(S, "_boto3_session", lambda: FakeSession())

    url = await S.put_bytes(key=KEY, data=TINY_PNG, content_type="image/png")
    assert url == f"http://127.0.0.1:9000/unhinted-media/{KEY}"
    assert put_calls[0]["Bucket"] == "unhinted-media"
    assert put_calls[0]["Key"] == KEY
    assert put_calls[0]["Body"] == TINY_PNG


@pytest.mark.asyncio
async def test_s3_delete_treats_missing_as_success(
    s3_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
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
