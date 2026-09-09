"""Media storage (S3-compatible) — unit tests with mocked boto3."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock

import pytest

from internal.media import storage as S

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def s3_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(S.settings, "s3_endpoint_url", "http://127.0.0.1:9000")
    monkeypatch.setattr(S.settings, "s3_access_key", "minioadmin")
    monkeypatch.setattr(S.settings, "s3_secret_key", "minioadmin")
    monkeypatch.setattr(S.settings, "s3_bucket", "unhinted-media")
    monkeypatch.setattr(S.settings, "s3_region", "us-east-1")
    monkeypatch.setattr(
        S.settings, "s3_public_base_url", "http://127.0.0.1:9000/unhinted-media"
    )


def test_media_storage_configured_false_when_endpoint_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(S.settings, "s3_endpoint_url", None)
    monkeypatch.setattr(S.settings, "s3_bucket", "unhinted-media")
    monkeypatch.setattr(S.settings, "s3_access_key", "x")
    monkeypatch.setattr(S.settings, "s3_secret_key", "y")
    assert S.media_storage_configured() is False


def test_media_storage_configured_true(s3_settings: None) -> None:
    assert S.media_storage_configured() is True


def test_parse_data_url_png() -> None:
    b64 = base64.b64encode(TINY_PNG).decode()
    data_url = f"data:image/png;base64,{b64}"
    raw, content_type = S.parse_data_url(data_url)
    assert raw == TINY_PNG
    assert content_type == "image/png"


def test_parse_data_url_rejects_non_data() -> None:
    with pytest.raises(S.MediaStorageError):
        S.parse_data_url("https://cdn.example/a.png")


def test_public_object_url(s3_settings: None) -> None:
    assert (
        S.public_object_url("sessions/abc/r1.png")
        == "http://127.0.0.1:9000/unhinted-media/sessions/abc/r1.png"
    )


@pytest.mark.asyncio
async def test_put_bytes_uploads_and_returns_public_url(
    s3_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_calls: list[dict] = []

    class FakeClient:
        def put_object(self, **kwargs):
            put_calls.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeSession:
        def client(self, *args, **kwargs):
            return FakeClient()

    monkeypatch.setattr(S, "_boto3_session", lambda: FakeSession())

    url = await S.put_bytes(
        key="sessions/s1/r1.png",
        data=TINY_PNG,
        content_type="image/png",
    )
    assert url == "http://127.0.0.1:9000/unhinted-media/sessions/s1/r1.png"
    assert len(put_calls) == 1
    assert put_calls[0]["Bucket"] == "unhinted-media"
    assert put_calls[0]["Key"] == "sessions/s1/r1.png"
    assert put_calls[0]["ContentType"] == "image/png"
    assert put_calls[0]["Body"] == TINY_PNG


@pytest.mark.asyncio
async def test_put_bytes_requires_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(S.settings, "s3_endpoint_url", None)
    with pytest.raises(S.MediaStorageError, match="S3_ENDPOINT"):
        await S.put_bytes(key="a.png", data=TINY_PNG, content_type="image/png")


@pytest.mark.asyncio
async def test_persist_generated_image_uploads_data_url(
    s3_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_put(*, key: str, data: bytes, content_type: str) -> str:
        assert key.startswith("sessions/")
        assert data == TINY_PNG
        assert content_type == "image/png"
        return f"http://127.0.0.1:9000/unhinted-media/{key}"

    monkeypatch.setattr(S, "put_bytes", fake_put)
    monkeypatch.setattr(S, "ensure_bucket", AsyncMock(return_value=None))
    b64 = base64.b64encode(TINY_PNG).decode()
    out = await S.persist_generated_image(
        f"data:image/png;base64,{b64}",
        key="sessions/s1/r1.png",
    )
    assert out.startswith("http://127.0.0.1:9000/unhinted-media/")


@pytest.mark.asyncio
async def test_persist_generated_image_passes_through_https(
    s3_settings: None,
) -> None:
    out = await S.persist_generated_image(
        "https://cdn.example/already.png",
        key="sessions/s1/r1.png",
    )
    assert out == "https://cdn.example/already.png"


@pytest.mark.asyncio
async def test_persist_generated_image_data_url_without_storage_stays_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(S.settings, "s3_endpoint_url", None)
    b64 = base64.b64encode(TINY_PNG).decode()
    data_url = f"data:image/png;base64,{b64}"
    out = await S.persist_generated_image(data_url, key="sessions/s1/r1.png")
    assert out == data_url


@pytest.mark.asyncio
async def test_ensure_bucket_creates_when_missing(
    s3_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    class FakeClient:
        def head_bucket(self, **kwargs):
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadBucket",
            )

        def create_bucket(self, **kwargs):
            calls.append(kwargs["Bucket"])

        def put_bucket_policy(self, **kwargs):
            calls.append("policy:" + kwargs["Bucket"])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeSession:
        def client(self, *args, **kwargs):
            return FakeClient()

    monkeypatch.setattr(S, "_boto3_session", lambda: FakeSession())

    await S.ensure_bucket()
    assert "unhinted-media" in calls
    assert any(c.startswith("policy:") for c in calls)
