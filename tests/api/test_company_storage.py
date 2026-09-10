"""Company storage config + local→S3 migrate HTTP API (ADR 0025)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from internal.config import settings
from internal.media import storage as S
from internal.media.config import load_snapshot, reset_snapshot_cache
from internal.memory import repos
from tests.api.helpers import auth_header, join_org, register_user

SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
KEY = "sessions/abc/r1-abcd1234.png"
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0c"
    b"IDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00"
    b"\x00IEND\xaeB`\x82"
)


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs):
        body = kwargs["Body"]
        if hasattr(body, "read"):
            body = body.read()
        self.objects[kwargs["Key"]] = body

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


def _base(company_id: str) -> str:
    return f"/api/companies/{company_id}/storage"


def _assert_no_secret(payload: Any) -> None:
    dumped = str(payload)
    assert SECRET not in dumped
    assert "secret_key_encrypted" not in dumped
    assert '"secret_key"' not in dumped


@pytest.fixture
def fake_s3(monkeypatch: pytest.MonkeyPatch) -> FakeS3:
    fake = FakeS3()

    class FakeSession:
        def client(self, *args, **kwargs):
            return fake

    monkeypatch.setattr(S, "_boto3_session", lambda: FakeSession())
    return fake


@pytest.mark.asyncio
async def test_storage_unauthenticated(client: AsyncClient) -> None:
    res = await client.get(f"/api/companies/{uuid.uuid4()}/storage/config")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_storage_member_forbidden(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    res = await client.get(
        f"{_base(company_id)}/config",
        headers=auth_header(member["access_token"]),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_put_config_never_leaks_secret(client: AsyncClient, fake_s3: FakeS3) -> None:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]
    put = await client.put(
        f"{_base(company_id)}/config",
        headers=headers,
        json={
            "bucket": "unhinted-media",
            "endpoint_url": "http://127.0.0.1:9000",
            "region": "us-east-1",
            "access_key": "garage",
            "secret_key": SECRET,
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    _assert_no_secret(body)
    assert body["backend"] == "local"
    assert body["bucket"] == "unhinted-media"
    assert body["secret_last4"] == SECRET[-4:]
    assert body["can_migrate"] is True

    got = await client.get(f"{_base(company_id)}/config", headers=headers)
    assert got.status_code == 200
    _assert_no_secret(got.json())
    assert got.json()["secret_last4"] == SECRET[-4:]

    again = await client.put(
        f"{_base(company_id)}/config",
        headers=headers,
        json={
            "bucket": "unhinted-media-2",
            "endpoint_url": "http://127.0.0.1:9000",
            "region": "ap-east-1",
            "access_key": "garage2",
        },
    )
    assert again.status_code == 200, again.text
    _assert_no_secret(again.json())
    assert again.json()["bucket"] == "unhinted-media-2"
    assert again.json()["secret_last4"] == SECRET[-4:]


@pytest.mark.asyncio
async def test_test_connection_ok(client: AsyncClient, fake_s3: FakeS3) -> None:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]
    res = await client.post(
        f"{_base(company_id)}/test",
        headers=headers,
        json={
            "bucket": "unhinted-media",
            "endpoint_url": "http://127.0.0.1:9000",
            "access_key": "garage",
            "secret_key": SECRET,
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    assert not any(k.startswith(".unhinted-probe/") for k in fake_s3.objects)


@pytest.mark.asyncio
async def test_migrate_copy_flip_rollback_clean(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_s3: FakeS3,
) -> None:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]
    user_id = uuid.UUID(data["user"]["id"])

    saved = await client.put(
        f"{_base(company_id)}/config",
        headers=headers,
        json={
            "bucket": "unhinted-media",
            "endpoint_url": "http://127.0.0.1:9000",
            "access_key": "garage",
            "secret_key": SECRET,
        },
    )
    assert saved.status_code == 200, saved.text

    await S.put_bytes(key=KEY, data=PNG, content_type="image/png")
    session = await repos.create_session(
        db_session,
        user_id=user_id,
        company_id=uuid.UUID(company_id),
    )
    await repos.insert_preview_image(
        db_session,
        session_id=session.id,
        url=KEY,
        plan={},
        format="single",
        role="primary",
        seq=0,
        status="ready",
    )
    await db_session.commit()

    started = await client.post(f"{_base(company_id)}/migrations", headers=headers)
    assert started.status_code == 201, started.text
    migration_id = started.json()["id"]

    current = None
    for _ in range(40):
        res = await client.get(f"{_base(company_id)}/migrations/current", headers=headers)
        assert res.status_code == 200, res.text
        current = res.json()
        if current["state"] in {"ready_to_flip", "failed"}:
            break
        await asyncio.sleep(0.05)
    assert current is not None
    assert current["state"] == "ready_to_flip", current
    assert KEY in fake_s3.objects

    conflict = await client.post(f"{_base(company_id)}/migrations", headers=headers)
    assert conflict.status_code == 409

    flipped = await client.post(
        f"{_base(company_id)}/migrations/{migration_id}/flip",
        headers=headers,
    )
    assert flipped.status_code == 200, flipped.text
    assert flipped.json()["state"] == "completed"
    cfg = await client.get(f"{_base(company_id)}/config", headers=headers)
    assert cfg.json()["backend"] == "s3"
    reset_snapshot_cache()
    await load_snapshot(db_session)
    assert S.media_backend() == "s3"

    rolled = await client.post(
        f"{_base(company_id)}/migrations/{migration_id}/rollback",
        headers=headers,
    )
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["state"] == "ready_to_flip"
    cfg = await client.get(f"{_base(company_id)}/config", headers=headers)
    assert cfg.json()["backend"] == "local"

    flipped_again = await client.post(
        f"{_base(company_id)}/migrations/{migration_id}/flip",
        headers=headers,
    )
    assert flipped_again.status_code == 200, flipped_again.text
    cleaned = await client.post(
        f"{_base(company_id)}/migrations/{migration_id}/clean",
        headers=headers,
    )
    assert cleaned.status_code == 200, cleaned.text
    assert cleaned.json()["state"] == "done"
    assert not (Path(settings.media_root) / KEY).exists()
