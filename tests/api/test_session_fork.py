"""Session fork routes (ADR 0017): transcript + draft copy, lineage, naming."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from internal.memory import repos
from internal.memory.models import PreviewImage, Session, SessionMessage
from tests.api.helpers import auth_header, register_user, seed_preview_session


async def _seed_messages(db_session, session_id: str, *roles: str) -> list[uuid.UUID]:
    """Seed messages with distinct increasing timestamps (ordering is created_at-only)."""
    base = datetime.now(UTC) - timedelta(minutes=len(roles))
    ids: list[uuid.UUID] = []
    for i, role in enumerate(roles):
        row = SessionMessage(
            session_id=uuid.UUID(session_id),
            role=role,
            content=f"{role} message {i}",
            metadata_={},
            created_at=base + timedelta(minutes=i),
        )
        db_session.add(row)
        await db_session.flush()
        ids.append(row.id)
    await db_session.commit()
    return ids


@pytest.mark.asyncio
async def test_fork_copies_transcript_and_records_lineage(client, db_session) -> None:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    source_id = created.json()["id"]
    await client.patch(f"/api/sessions/{source_id}", headers=headers, json={"title": "test"})
    msg_ids = await _seed_messages(db_session, source_id, "user", "assistant", "user", "assistant")

    res = await client.post(
        f"/api/sessions/{source_id}/fork",
        headers=headers,
        json={"message_id": str(msg_ids[1])},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    fork_id = body["session"]["id"]
    assert fork_id != source_id

    # Transcript up to and including the fork point, original order + timestamps.
    contents = [m["content"] for m in body["messages"]]
    assert contents == ["user message 0", "assistant message 1"]
    assert body["messages"][-1]["metadata"]["fork_point"] is True
    assert body["messages"][0]["metadata"].get("fork_point") is None

    # Lineage on the fork.
    origin = body["forked_from"]
    assert origin["session_id"] == source_id
    assert origin["message_id"] == str(msg_ids[1])
    assert origin["title"] == "test"
    # No preview anywhere → nothing to notify.
    assert body["preview_note"] is None

    # Naming: "(n) base".
    listed = await client.get("/api/sessions", headers=headers, params={"company_id": company_id})
    fork_row = next(s for s in listed.json()["sessions"] if s["id"] == fork_id)
    assert fork_row["title"] == "(1) test"
    assert fork_row["pinned"] is False

    # Source message now lists the fork.
    src = await client.get(f"/api/sessions/{source_id}/messages", headers=headers)
    assert src.status_code == 200
    src_msgs = src.json()["messages"]
    forked_msg = next(m for m in src_msgs if m["id"] == str(msg_ids[1]))
    assert [f["session_id"] for f in forked_msg["forks"]] == [fork_id]
    assert forked_msg["forks"][0]["title"] == "(1) test"
    # Untouched messages carry no forks; source itself has no origin.
    assert all(m["forks"] == [] for m in src_msgs if m["id"] != str(msg_ids[1]))
    assert src.json()["forked_from"] is None

    # Hydrating the fork returns the same origin.
    fork_view = await client.get(f"/api/sessions/{fork_id}/messages", headers=headers)
    assert fork_view.json()["forked_from"]["session_id"] == source_id


@pytest.mark.asyncio
async def test_fork_naming_counts_per_direct_source(client, db_session) -> None:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    source_id = created.json()["id"]
    await client.patch(f"/api/sessions/{source_id}", headers=headers, json={"title": "test"})
    msg_ids = await _seed_messages(db_session, source_id, "user", "assistant")

    titles: list[str] = []
    first_fork_id = None
    for _ in range(2):
        res = await client.post(
            f"/api/sessions/{source_id}/fork",
            headers=headers,
            json={"message_id": str(msg_ids[1])},
        )
        assert res.status_code == 201, res.text
        fork_id = res.json()["session"]["id"]
        first_fork_id = first_fork_id or fork_id
        listed = await client.get("/api/sessions", headers=headers, params={"company_id": company_id})
        titles.append(next(s for s in listed.json()["sessions"] if s["id"] == fork_id)["title"])
    assert titles == ["(1) test", "(2) test"]

    # Fork of a fork: prefix stripped, counter restarts against the direct source.
    assert first_fork_id is not None
    res = await client.get(f"/api/sessions/{first_fork_id}/messages", headers=headers)
    fork_msg_id = res.json()["messages"][-1]["id"]
    res2 = await client.post(
        f"/api/sessions/{first_fork_id}/fork",
        headers=headers,
        json={"message_id": fork_msg_id},
    )
    assert res2.status_code == 201, res2.text
    nested_id = res2.json()["session"]["id"]
    listed = await client.get("/api/sessions", headers=headers, params={"company_id": company_id})
    nested = next(s for s in listed.json()["sessions"] if s["id"] == nested_id)
    assert nested["title"] == "(1) test"
    assert res2.json()["forked_from"]["title"] == "(1) test"


@pytest.mark.asyncio
async def test_fork_copies_preview_draft_with_fresh_token(client, db_session) -> None:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    source_id = await seed_preview_session(db_session, user_id=user_id, company_id=company_id)
    msg_ids = await _seed_messages(db_session, str(source_id), "user", "assistant")

    # Time-aligned copy (ADR 0017): align the draft with the fork-point message,
    # mimicking the same-transaction write of a real preview turn.
    fork_msg = await db_session.get(SessionMessage, msg_ids[1])
    assert fork_msg is not None
    source_draft_row = await repos.get_latest_preview_draft(db_session, source_id)
    assert source_draft_row is not None
    source_draft_row.created_at = fork_msg.created_at
    await db_session.commit()

    res = await client.post(
        f"/api/sessions/{source_id}/fork",
        headers=headers,
        json={"message_id": str(msg_ids[1])},
    )
    assert res.status_code == 201, res.text
    # Same-turn preview (equal timestamps) is included; nothing surprising to note.
    assert res.json()["preview_note"] is None
    fork_id = uuid.UUID(res.json()["session"]["id"])
    assert res.json()["session"]["mode"] == "PREVIEW"

    source_draft = await repos.get_latest_preview_draft(db_session, source_id)
    fork_draft = await repos.get_latest_preview_draft(db_session, fork_id)
    assert source_draft is not None and fork_draft is not None
    assert fork_draft.revision == 1
    assert fork_draft.copy == source_draft.copy
    assert fork_draft.image_url == source_draft.image_url
    # Fresh approval token — never shared across sessions (ADR 0003).
    assert fork_draft.approval_token != source_draft.approval_token

    # Media rows duplicated into the fork and media_ids remapped.
    fork_images = list(
        (
            await db_session.scalars(
                select(PreviewImage).where(PreviewImage.session_id == fork_id)
            )
        ).all()
    )
    assert len(fork_images) == 1
    assert fork_images[0].url == "placeholder://seed"
    assert fork_draft.media_ids == [fork_images[0].id]
    assert fork_images[0].id not in list(source_draft.media_ids)

    # Draft state lands on the fork session; confirm-ish state stays clean.
    fork_session = await db_session.get(Session, fork_id)
    assert fork_session is not None
    assert fork_session.state["revision"] == 1
    assert fork_session.state["approval_token"] == fork_draft.approval_token
    assert fork_session.state["draft"] == source_draft.copy
    assert fork_session.state["pending_confirm"] is False
    assert fork_session.status == "active"

    # The fork's media is served under its own session id.
    media = await client.get(f"/api/sessions/{fork_id}/media", headers=headers)
    assert media.status_code == 200
    assert [m["id"] for m in media.json()["media"]] == [str(fork_images[0].id)]


@pytest.mark.asyncio
async def test_fork_message_not_found(client, db_session) -> None:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]
    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    source_id = created.json()["id"]
    await _seed_messages(db_session, source_id, "user")

    res = await client.post(
        f"/api/sessions/{source_id}/fork",
        headers=headers,
        json={"message_id": str(uuid.uuid4())},
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Message not found"


@pytest.mark.asyncio
async def test_fork_requires_ownership(client, db_session) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    created = await client.post(
        "/api/sessions",
        headers=auth_header(owner["access_token"]),
        json={"company_id": company_id},
    )
    source_id = created.json()["id"]
    msg_ids = await _seed_messages(db_session, source_id, "user", "assistant")

    other = await register_user(
        client,
        email=f"oth-{uuid.uuid4().hex[:8]}@example.com",
        organization_name="Other Co",
    )
    res = await client.post(
        f"/api/sessions/{source_id}/fork",
        headers=auth_header(other["access_token"]),
        json={"message_id": str(msg_ids[1])},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_fork_survives_source_delete_with_snapshot_title(client, db_session) -> None:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]

    created = await client.post("/api/sessions", headers=headers, json={"company_id": company_id})
    source_id = created.json()["id"]
    await client.patch(f"/api/sessions/{source_id}", headers=headers, json={"title": "test"})
    msg_ids = await _seed_messages(db_session, source_id, "user", "assistant")

    res = await client.post(
        f"/api/sessions/{source_id}/fork",
        headers=headers,
        json={"message_id": str(msg_ids[1])},
    )
    assert res.status_code == 201, res.text
    fork_id = res.json()["session"]["id"]

    deleted = await client.delete(f"/api/sessions/{source_id}", headers=headers)
    assert deleted.status_code == 204

    fork_view = await client.get(f"/api/sessions/{fork_id}/messages", headers=headers)
    assert fork_view.status_code == 200
    origin = fork_view.json()["forked_from"]
    assert origin["session_id"] is None  # FK SET NULL
    assert origin["message_id"] == str(msg_ids[1])
    assert origin["title"] == "test"  # snapshot fallback


@pytest.mark.asyncio
async def test_fork_before_preview_existed_carries_no_draft(client, db_session) -> None:
    """Preview postdates the fork point → fork has no draft, note not_carried_later."""
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    # Draft gets created_at = now(); seeded messages sit in the past.
    source_id = await seed_preview_session(db_session, user_id=user_id, company_id=company_id)
    msg_ids = await _seed_messages(db_session, str(source_id), "user", "assistant")

    res = await client.post(
        f"/api/sessions/{source_id}/fork",
        headers=headers,
        json={"message_id": str(msg_ids[1])},
    )
    assert res.status_code == 201, res.text
    assert res.json()["preview_note"] == "not_carried_later"

    fork_id = uuid.UUID(res.json()["session"]["id"])
    assert await repos.get_latest_preview_draft(db_session, fork_id) is None
    fork_session = await db_session.get(Session, fork_id)
    assert fork_session is not None
    assert fork_session.mode == "CHAT"
    assert fork_session.state == {}


@pytest.mark.asyncio
async def test_fork_keeps_fork_point_revision_when_source_edited_after(
    client, db_session
) -> None:
    """Edits after the fork-point message don't travel; note carried_stale."""
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    source_id = await seed_preview_session(db_session, user_id=user_id, company_id=company_id)
    msg_ids = await _seed_messages(db_session, str(source_id), "user", "assistant")

    fork_msg = await db_session.get(SessionMessage, msg_ids[1])
    assert fork_msg is not None
    at_fork = fork_msg.created_at

    # rev 1 = same-turn as the fork message; rev 2 = manual edit afterwards.
    rev1 = await repos.get_latest_preview_draft(db_session, source_id)
    assert rev1 is not None
    rev1.created_at = at_fork
    await repos.upsert_preview_draft(
        db_session,
        session_id=source_id,
        revision=2,
        copy={"caption": "edited later", "hashtags": ["#new"], "cta": ""},
        image_url="placeholder://seed",
        image_plan=None,
        media_ids=list(rev1.media_ids),
        source_signal_ids=[],
        approval_token="test-approval-token-002",
        platform="instagram",
        created_at=at_fork + timedelta(seconds=30),
    )
    await db_session.commit()

    res = await client.post(
        f"/api/sessions/{source_id}/fork",
        headers=headers,
        json={"message_id": str(msg_ids[1])},
    )
    assert res.status_code == 201, res.text
    assert res.json()["preview_note"] == "carried_stale"

    fork_id = uuid.UUID(res.json()["session"]["id"])
    fork_draft = await repos.get_latest_preview_draft(db_session, fork_id)
    assert fork_draft is not None
    assert fork_draft.copy["caption"] == "seed"  # rev 1, not the later edit
    # Copied row keeps the source timeline so fork-of-fork stays aligned.
    assert fork_draft.created_at == at_fork


@pytest.mark.asyncio
async def test_fork_of_fork_keeps_preview(client, db_session) -> None:
    """Copied draft keeps the source created_at, so a second-generation fork
    still finds a draft as-of its (original-timestamped) messages."""
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    source_id = await seed_preview_session(db_session, user_id=user_id, company_id=company_id)
    msg_ids = await _seed_messages(db_session, str(source_id), "user", "assistant")

    fork_msg = await db_session.get(SessionMessage, msg_ids[1])
    assert fork_msg is not None
    draft = await repos.get_latest_preview_draft(db_session, source_id)
    assert draft is not None
    draft.created_at = fork_msg.created_at
    await db_session.commit()

    first = await client.post(
        f"/api/sessions/{source_id}/fork",
        headers=headers,
        json={"message_id": str(msg_ids[1])},
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["session"]["id"]

    first_msgs = await client.get(f"/api/sessions/{first_id}/messages", headers=headers)
    last_msg_id = first_msgs.json()["messages"][-1]["id"]
    second = await client.post(
        f"/api/sessions/{first_id}/fork",
        headers=headers,
        json={"message_id": last_msg_id},
    )
    assert second.status_code == 201, second.text
    assert second.json()["preview_note"] is None

    second_draft = await repos.get_latest_preview_draft(
        db_session, uuid.UUID(second.json()["session"]["id"])
    )
    assert second_draft is not None
    assert second_draft.copy["caption"] == "seed"
    assert second_draft.created_at == fork_msg.created_at
