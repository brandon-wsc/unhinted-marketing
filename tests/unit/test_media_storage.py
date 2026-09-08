"""Media storage (ADR 0024) — local on-prem + AWS S3, no MinIO."""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest
from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cmd.api.routes.media import router as media_router
from internal.config import settings
from internal.media import backends as B
from internal.media import storage as S

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def cloud_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "deployment_mode", "cloud")
    monkeypatch.setattr(settings, "s3_bucket", "unhinted-media")
    monkeypatch.setattr(settings, "s3_region", "ap-east-1")
    monkeypatch.setattr(settings, "s3_access_key", "AKIAEXAMPLE")
    monkeypatch.setattr(settings, "s3_secret_key", "secret")
    monkeypatch.setattr(settings, "s3_public_base_url", None)


_KEY_RE = re.compile(r"^sessions/[A-Za-z0-9_-]+/r\d+-[0-9a-f]{8}\.[a-z]+$")


def test_media_object_key_distinct_for_same_revision() -> None:
    a = S.media_object_key(session_id="abc", revision=1)
    b = S.media_object_key(session_id="abc", revision=1)
    assert a != b
    assert _KEY_RE.match(a)
    assert _KEY_RE.match(b)
    assert a.endswith(".png")
    assert b.endswith(".png")


def test_normalize_key_rejects_traversal() -> None:
    with pytest.raises(S.MediaStorageError, match="Invalid"):
        B.normalize_key("../etc/passwd")
    with pytest.raises(S.MediaStorageError, match="Invalid"):
        B.normalize_key("/absolute")
    with pytest.raises(S.MediaStorageError, match="Invalid"):
        B.normalize_key("")
    assert B.normalize_key("sessions/abc/r1.png") == "sessions/abc/r1.png"


def test_assert_media_store_ready_onprem_needs_nothing() -> None:
    S.assert_media_store_ready()


def test_assert_media_store_ready_cloud_requires_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "deployment_mode", "cloud")
    monkeypatch.setattr(settings, "s3_bucket", None)
    monkeypatch.setattr(settings, "s3_access_key", "x")
    monkeypatch.setattr(settings, "s3_secret_key", "y")
    with pytest.raises(RuntimeError, match="S3_BUCKET"):
        S.assert_media_store_ready()


def test_assert_media_store_ready_cloud_partial_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "deployment_mode", "cloud")
    monkeypatch.setattr(settings, "s3_bucket", "unhinted-media")
    monkeypatch.setattr(settings, "s3_access_key", "only-access")
    monkeypatch.setattr(settings, "s3_secret_key", None)
    with pytest.raises(RuntimeError, match="S3_ACCESS_KEY"):
        S.assert_media_store_ready()


def test_assert_media_store_ready_cloud_iam_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "deployment_mode", "cloud")
    monkeypatch.setattr(settings, "s3_bucket", "unhinted-media")
    monkeypatch.setattr(settings, "s3_access_key", None)
    monkeypatch.setattr(settings, "s3_secret_key", None)
    S.assert_media_store_ready()


def test_assert_media_store_ready_cloud_keys_ok(cloud_s3: None) -> None:
    S.assert_media_store_ready()


def test_resolve_onprem_is_local() -> None:
    store = B.resolve_media_store()
    assert isinstance(store, B.LocalStore)


def test_resolve_cloud_is_s3(cloud_s3: None) -> None:
    store = B.resolve_media_store()
    assert isinstance(store, B.S3Store)


def test_s3_public_url_virtual_hosted(cloud_s3: None) -> None:
    url = B.S3Store().public_url("sessions/abc/r1.png")
    assert url == "https://unhinted-media.s3.ap-east-1.amazonaws.com/sessions/abc/r1.png"


def test_s3_public_url_custom_base(cloud_s3: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "s3_public_base_url", "https://cdn.example/media")
    url = B.S3Store().public_url("sessions/abc/r1.png")
    assert url == "https://cdn.example/media/sessions/abc/r1.png"


def test_parse_data_url_png() -> None:
    b64 = base64.b64encode(TINY_PNG).decode()
    data_url = f"data:image/png;base64,{b64}"
    raw, content_type = S.parse_data_url(data_url)
    assert raw == TINY_PNG
    assert content_type == "image/png"


def test_parse_data_url_rejects_non_data() -> None:
    with pytest.raises(S.MediaStorageError):
        S.parse_data_url("https://cdn.example/a.png")


@pytest.mark.asyncio
async def test_local_put_bytes_writes_file() -> None:
    url = await S.put_bytes(
        key="sessions/s1/r1.png",
        data=TINY_PNG,
        content_type="image/png",
    )
    assert url.endswith("/api/media/sessions/s1/r1.png")
    stored = Path(settings.media_root) / "sessions" / "s1" / "r1.png"
    assert stored.read_bytes() == TINY_PNG


@pytest.mark.asyncio
async def test_persist_generated_image_uploads_data_url() -> None:
    b64 = base64.b64encode(TINY_PNG).decode()
    key = S.media_object_key(session_id="s1", revision=1)
    out = await S.persist_generated_image(
        f"data:image/png;base64,{b64}",
        key=key,
    )
    assert out == key
    assert re.search(r"^sessions/s1/r1-[0-9a-f]{8}\.png$", out)
    path = S.local_media_path(key)
    assert path is not None
    assert path.read_bytes() == TINY_PNG


@pytest.mark.asyncio
async def test_persist_generated_image_sniffs_jpeg_mislabeled_png() -> None:
    jpeg = b"\xff\xd8\xff" + b"\x00" * 8
    b64 = base64.b64encode(jpeg).decode()
    key = S.media_object_key(session_id="s1", revision=1)
    out = await S.persist_generated_image(
        f"data:image/png;base64,{b64}",
        key=key,
    )
    jpg_key = key[:-4] + ".jpg"
    assert out == jpg_key
    assert re.search(r"^sessions/s1/r1-[0-9a-f]{8}\.jpg$", out)
    path = S.local_media_path(jpg_key)
    assert path is not None
    assert path.read_bytes() == jpeg


@pytest.mark.asyncio
async def test_persist_generated_image_rejects_unknown_scheme() -> None:
    with pytest.raises(S.MediaStorageError, match="Unsupported image ref scheme"):
        await S.persist_generated_image(
            "placeholder://local/x",
            key="sessions/s1/r1.png",
        )
    with pytest.raises(S.MediaStorageError, match="Unsupported image ref scheme"):
        await S.persist_generated_image(
            "ftp://cdn.example/a.png",
            key="sessions/s1/r1.png",
        )
    with pytest.raises(S.MediaStorageError, match="Unsupported image ref scheme"):
        await S.persist_generated_image("", key="sessions/s1/r1.png")


@pytest.mark.asyncio
async def test_s3_iam_omits_static_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "deployment_mode", "cloud")
    monkeypatch.setattr(settings, "s3_bucket", "unhinted-media")
    monkeypatch.setattr(settings, "s3_region", "us-east-1")
    monkeypatch.setattr(settings, "s3_access_key", None)
    monkeypatch.setattr(settings, "s3_secret_key", None)
    monkeypatch.setattr(settings, "s3_public_base_url", None)
    client_kwargs: list[dict] = []

    class FakeClient:
        def put_object(self, **kwargs):
            return None

    class CapturingSession:
        def client(self, service: str, **kwargs):
            client_kwargs.append(kwargs)
            return FakeClient()

    monkeypatch.setattr(B.boto3.session, "Session", lambda: CapturingSession())
    await S.put_bytes(key="sessions/s1/r1.png", data=TINY_PNG, content_type="image/png")
    assert "aws_access_key_id" not in client_kwargs[0]
    assert "endpoint_url" not in client_kwargs[0]


@pytest.mark.asyncio
async def test_persist_generated_image_passes_through_https() -> None:
    out = await S.persist_generated_image(
        "https://cdn.example/already.png",
        key="sessions/s1/r1.png",
    )
    assert out == "https://cdn.example/already.png"


@pytest.mark.asyncio
async def test_put_bytes_s3_no_custom_endpoint(
    cloud_s3: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_calls: list[dict] = []
    client_kwargs: list[dict] = []

    class FakeClient:
        def put_object(self, **kwargs):
            put_calls.append(kwargs)

    class CapturingSession:
        def client(self, service: str, **kwargs):
            assert service == "s3"
            assert "endpoint_url" not in kwargs
            client_kwargs.append(kwargs)
            return FakeClient()

    monkeypatch.setattr(B.boto3.session, "Session", lambda: CapturingSession())

    url = await S.put_bytes(
        key="sessions/s1/r1.png",
        data=TINY_PNG,
        content_type="image/png",
    )
    assert url == "https://unhinted-media.s3.ap-east-1.amazonaws.com/sessions/s1/r1.png"
    assert len(put_calls) == 1
    assert put_calls[0]["Bucket"] == "unhinted-media"
    assert put_calls[0]["Key"] == "sessions/s1/r1.png"
    assert put_calls[0]["ContentType"] == "image/png"
    assert put_calls[0]["Body"] == TINY_PNG
    assert client_kwargs[0]["region_name"] == "ap-east-1"
    assert client_kwargs[0]["aws_access_key_id"] == "AKIAEXAMPLE"


@pytest.mark.asyncio
async def test_s3_put_wraps_client_error(
    cloud_s3: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeClient:
        def put_object(self, **kwargs):
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "no"}},
                "PutObject",
            )

    monkeypatch.setattr(B, "_s3_client", lambda: FakeClient())
    with pytest.raises(S.MediaStorageError, match="put_object"):
        await S.put_bytes(key="a.png", data=TINY_PNG, content_type="image/png")


def test_local_media_path_none_on_cloud(cloud_s3: None) -> None:
    assert S.local_media_path("sessions/s1/r1.png") is None


def test_get_media_roundtrip() -> None:
    app = FastAPI()
    app.include_router(media_router, prefix="/api")
    client = TestClient(app)
    root = Path(settings.media_root)
    dest = root / "sessions" / "abc" / "r1.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(TINY_PNG)

    resp = client.get("/api/media/sessions/abc/r1.png")
    assert resp.status_code == 200
    assert resp.content == TINY_PNG
    assert resp.headers["content-type"].startswith("image/png")


def test_get_media_missing_404() -> None:
    app = FastAPI()
    app.include_router(media_router, prefix="/api")
    client = TestClient(app)
    resp = client.get("/api/media/sessions/nope/r1.png")
    assert resp.status_code == 404


def test_get_media_traversal_404() -> None:
    app = FastAPI()
    app.include_router(media_router, prefix="/api")
    client = TestClient(app)
    resp = client.get("/api/media/../storage.py")
    assert resp.status_code == 404


def test_get_media_cloud_404(cloud_s3: None) -> None:
    app = FastAPI()
    app.include_router(media_router, prefix="/api")
    client = TestClient(app)
    resp = client.get("/api/media/sessions/abc/r1.png")
    assert resp.status_code == 404


def test_resolve_stored_url_key_uses_current_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "web_base_url", "https://old.example")
    key = "sessions/s1/r1-abcd1234.png"
    assert S.resolve_stored_url(key) == "https://old.example/api/media/" + key
    monkeypatch.setattr(settings, "web_base_url", "https://new.example")
    assert S.resolve_stored_url(key) == "https://new.example/api/media/" + key


def test_resolve_stored_url_rewrites_baked_api_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "web_base_url", "https://new.example")
    baked = "https://old.example/api/media/sessions/s1/r1-abcd1234.png"
    assert (
        S.resolve_stored_url(baked)
        == "https://new.example/api/media/sessions/s1/r1-abcd1234.png"
    )
    assert (
        S.resolve_stored_url("/api/media/sessions/s1/r1-abcd1234.png")
        == "https://new.example/api/media/sessions/s1/r1-abcd1234.png"
    )


def test_resolve_stored_url_rewrites_s3_virtual_hosted(
    cloud_s3: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    baked = "https://unhinted-media.s3.ap-east-1.amazonaws.com/sessions/s1/r1.png"
    assert S.resolve_stored_url(baked) == baked
    monkeypatch.setattr(settings, "s3_public_base_url", "https://cdn.example/media")
    assert (
        S.resolve_stored_url(baked) == "https://cdn.example/media/sessions/s1/r1.png"
    )


def test_resolve_stored_url_passthrough_external_and_placeholder() -> None:
    assert S.resolve_stored_url("https://cdn.openai.com/a.png") == "https://cdn.openai.com/a.png"
    assert S.resolve_stored_url("placeholder://local/x") == "placeholder://local/x"
    assert S.resolve_stored_url(None) is None
    assert S.resolve_stored_url("") is None


def test_is_stored_image_ref() -> None:
    assert S.is_stored_image_ref("sessions/s1/r1-abcd1234.png")
    assert S.is_stored_image_ref("https://cdn.example/a.png")
    assert not S.is_stored_image_ref("placeholder://seed")
    assert not S.is_stored_image_ref(None)
    assert not S.is_stored_image_ref("")
