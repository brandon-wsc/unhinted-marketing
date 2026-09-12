"""Local media GET + session-delete GC (ADR 0024)."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pytest

from internal.config import settings
from internal.media.storage import put_bytes
from internal.memory.models import SessionMessage
from tests.api.helpers import auth_header, register_user, seed_preview_session

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0c"
    b"IDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00"
    b"\x00IEND\xaeB`\x82"
)


@pytest.mark.asyncio
async def test_get_media_unauthenticated_roundtrip(client) -> None:
    key = "sessions/t/r1-abcd1234.png"
    await put_bytes(key=key, data=PNG, content_type="image/png")
    res = await client.get(f"/api/media/{key}")
    assert res.status_code == 200
    assert res.content == PNG
    assert res.headers["content-type"].startswith("image/png")


@pytest.mark.asyncio
async def test_get_media_rejects_path_traversal(client) -> None:
    res = await client.get("/api/media/../secret")
    assert res.status_code == 404
    nested = await client.get("/api/media/sessions/../../etc/passwd")
    assert nested.status_code == 404
    missing = await client.get("/api/media/sessions/nope/r1-deadbeef.png")
    assert missing.status_code == 404


async def _upload_second_slot(client, headers, session_id: uuid.UUID) -> tuple[str, str]:
    added = await client.post(
        f"/api/sessions/{session_id}/media",
        headers=headers,
        json={"format": "single"},
    )
    assert added.status_code == 200, added.text
    pending_id = added.json()["media"][1]["id"]
    uploaded = await client.post(
        f"/api/sessions/{session_id}/media/{pending_id}/upload",
        headers=headers,
        files={"file": ("slot.png", io.BytesIO(PNG), "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    url = uploaded.json()["media"][1]["url"]
    path = urlparse(url).path
    return url, path


@pytest.mark.asyncio
async def test_delete_session_reclaims_unref_object(client, db_session) -> None:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    session_id = await seed_preview_session(
        db_session, user_id=user_id, company_id=company_id
    )
    _url, path = await _upload_second_slot(client, headers, session_id)
    assert (await client.get(path)).status_code == 200

    deleted = await client.delete(f"/api/sessions/{session_id}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get(path)).status_code == 404


@pytest.mark.asyncio
async def test_delete_session_skips_keys_still_used_by_fork(client, db_session) -> None:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    source_id = await seed_preview_session(
        db_session, user_id=user_id, company_id=company_id
    )
    _url, path = await _upload_second_slot(client, headers, source_id)

    base = datetime.now(UTC) + timedelta(seconds=1)
    ids: list[uuid.UUID] = []
    for i, role in enumerate(("user", "assistant")):
        row = SessionMessage(
            session_id=source_id,
            role=role,
            content=f"{role} {i}",
            metadata_={},
        )
        row.created_at = base + timedelta(seconds=i)
        db_session.add(row)
        await db_session.flush()
        ids.append(row.id)
    await db_session.commit()

    forked = await client.post(
        f"/api/sessions/{source_id}/fork",
        headers=headers,
        json={"message_id": str(ids[1])},
    )
    assert forked.status_code == 201, forked.text
    fork_id = forked.json()["session"]["id"]

    deleted_source = await client.delete(f"/api/sessions/{source_id}", headers=headers)
    assert deleted_source.status_code == 204
    assert (await client.get(path)).status_code == 200

    deleted_fork = await client.delete(f"/api/sessions/{fork_id}", headers=headers)
    assert deleted_fork.status_code == 204
    assert (await client.get(path)).status_code == 404
    root = Path(settings.media_root)
    leftover = list(root.rglob("*.png")) if root.exists() else []
    assert leftover == []


@pytest.mark.asyncio
async def test_delete_session_still_commits_when_gc_collect_fails(
    client, db_session, monkeypatch
) -> None:
    """Failed key collect skips reclaim but never blocks the delete (ADR 0024 §5)."""
    import cmd.api.routes.sessions as session_routes

    async def boom(db, session_id):
        raise RuntimeError("collect exploded")

    monkeypatch.setattr(session_routes, "collect_session_store_keys", boom)

    data = await register_user(client)
    headers = auth_header(data["access_token"])
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    session_id = await seed_preview_session(
        db_session, user_id=user_id, company_id=company_id
    )
    _url, path = await _upload_second_slot(client, headers, session_id)

    deleted = await client.delete(f"/api/sessions/{session_id}", headers=headers)
    assert deleted.status_code == 204
    # Orphan bytes are acceptable — the object is left behind, not a dangling ref.
    assert (await client.get(path)).status_code == 200


@pytest.mark.asyncio
async def test_delete_session_object_delete_runs_after_commit(
    client, db_session, session_factory, monkeypatch
) -> None:
    """Crash-safety invariant: object delete runs after the DB commit (ADR 0024 §5)."""
    from internal.media import gc as gc_mod
    from internal.memory import repos

    real_delete = gc_mod.delete_key
    seen_committed: list[bool] = []

    async def spy_delete(key: str) -> None:
        async with session_factory() as db:
            seen_committed.append(await repos.get_session(db, session_id) is None)
        await real_delete(key)

    monkeypatch.setattr(gc_mod, "delete_key", spy_delete)

    data = await register_user(client)
    headers = auth_header(data["access_token"])
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    session_id = await seed_preview_session(
        db_session, user_id=user_id, company_id=company_id
    )
    _url, path = await _upload_second_slot(client, headers, session_id)

    deleted = await client.delete(f"/api/sessions/{session_id}", headers=headers)
    assert deleted.status_code == 204
    assert seen_committed and all(seen_committed)
    assert (await client.get(path)).status_code == 404
