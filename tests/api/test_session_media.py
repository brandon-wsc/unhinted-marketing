"""Preview media HTTP: plan / regen / add / remove / upload (ADR 0008)."""

from __future__ import annotations

import io
import uuid
from urllib.parse import urlparse

import pytest

from internal.memory import repos
from internal.memory.models import Session
from tests.api.helpers import auth_header, register_user, seed_preview_session


@pytest.mark.asyncio
async def test_session_media_list_plan_regen_add(client, db_session, monkeypatch) -> None:
    monkeypatch.setattr("internal.llm.router.has_llm_credentials", lambda: False)

    data = await register_user(client)
    token = data["access_token"]
    headers = auth_header(token)
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])

    session_id = await seed_preview_session(
        db_session,
        user_id=user_id,
        company_id=company_id,
    )

    listed = await client.get(f"/api/sessions/{session_id}/media", headers=headers)
    assert listed.status_code == 200, listed.text
    media = listed.json()["media"]
    assert len(media) == 1
    image_id = media[0]["id"]
    assert media[0]["plan"]["prompt"] == "seed plan"

    patched = await client.patch(
        f"/api/sessions/{session_id}/media/{image_id}/plan",
        headers=headers,
        json={"plan": {"prompt": "edited", "format": "single", "style": "clean"}},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["revision"] == 2
    assert body["media"][0]["plan"]["prompt"] == "edited"
    assert body["media"][0]["id"] != image_id
    new_id = body["media"][0]["id"]

    regen = await client.post(
        f"/api/sessions/{session_id}/media/{new_id}/regen",
        headers=headers,
    )
    assert regen.status_code == 200, regen.text
    regen_body = regen.json()
    assert regen_body["revision"] == 3
    assert regen_body["media"][0]["url"]
    assert regen_body["media"][0]["id"] != new_id

    added = await client.post(
        f"/api/sessions/{session_id}/media",
        headers=headers,
        json={"format": "single"},
    )
    assert added.status_code == 200, added.text
    add_body = added.json()
    assert add_body["revision"] == 4
    assert len(add_body["media"]) == 2
    assert add_body["media"][1]["status"] == "pending"


@pytest.mark.asyncio
async def test_session_media_remove_and_upload(client, db_session) -> None:

    data = await register_user(client)
    token = data["access_token"]
    headers = auth_header(token)
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])

    session_id = await seed_preview_session(
        db_session,
        user_id=user_id,
        company_id=company_id,
    )

    listed = await client.get(f"/api/sessions/{session_id}/media", headers=headers)
    image_id = listed.json()["media"][0]["id"]

    # Cannot remove the last remaining image
    refuse = await client.post(
        f"/api/sessions/{session_id}/media/{image_id}/remove",
        headers=headers,
    )
    assert refuse.status_code == 400, refuse.text

    added = await client.post(
        f"/api/sessions/{session_id}/media",
        headers=headers,
        json={"format": "single"},
    )
    assert added.status_code == 200, added.text
    media = added.json()["media"]
    assert len(media) == 2
    second_id = media[1]["id"]

    removed = await client.post(
        f"/api/sessions/{session_id}/media/{second_id}/remove",
        headers=headers,
    )
    assert removed.status_code == 200, removed.text
    rem_body = removed.json()
    assert rem_body["revision"] == 3
    assert len(rem_body["media"]) == 1
    assert rem_body["media"][0]["id"] == image_id

    # Re-add then upload over the pending slot
    added2 = await client.post(
        f"/api/sessions/{session_id}/media",
        headers=headers,
        json={"format": "single"},
    )
    pending_id = added2.json()["media"][1]["id"]
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0c"
        b"IDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00"
        b"\x00IEND\xaeB`\x82"
    )
    uploaded = await client.post(
        f"/api/sessions/{session_id}/media/{pending_id}/upload",
        headers=headers,
        files={"file": ("slot.png", io.BytesIO(png), "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    up_body = uploaded.json()
    assert len(up_body["media"]) == 2
    slot = up_body["media"][1]
    assert slot["id"] != pending_id
    assert slot["status"] == "ready"
    assert "/api/media/" in (slot["url"] or "")
    parsed = urlparse(slot["url"])
    fetched = await client.get(parsed.path)
    assert fetched.status_code == 200
    assert fetched.content == png
    db_session.expire_all()
    image_row = await repos.get_preview_image(db_session, uuid.UUID(slot["id"]))
    assert image_row is not None
    assert image_row.url is not None
    assert image_row.url.startswith("sessions/")
    assert not image_row.url.startswith("http")

    bad = await client.post(
        f"/api/sessions/{session_id}/media/{slot['id']}/upload",
        headers=headers,
        files={"file": ("notes.txt", io.BytesIO(b"not-an-image"), "text/plain")},
    )
    assert bad.status_code == 400, bad.text


@pytest.mark.asyncio
async def test_session_media_upload_size_and_empty_guards(client, db_session) -> None:
    """ADR 0024 §4: uploads capped at 10 MB; empty rejected."""
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    session_id = await seed_preview_session(
        db_session, user_id=user_id, company_id=company_id
    )

    added = await client.post(
        f"/api/sessions/{session_id}/media",
        headers=headers,
        json={"format": "single"},
    )
    assert added.status_code == 200, added.text
    pending_id = added.json()["media"][1]["id"]

    too_big = b"\x89PNG\r\n\x1a\n" + b"0" * (10 * 1024 * 1024)
    big = await client.post(
        f"/api/sessions/{session_id}/media/{pending_id}/upload",
        headers=headers,
        files={"file": ("big.png", io.BytesIO(too_big), "image/png")},
    )
    assert big.status_code == 400, big.text
    assert "too large" in big.json()["detail"].lower()

    empty = await client.post(
        f"/api/sessions/{session_id}/media/{pending_id}/upload",
        headers=headers,
        files={"file": ("empty.png", io.BytesIO(b""), "image/png")},
    )
    assert empty.status_code == 400, empty.text


@pytest.mark.asyncio
async def test_session_media_format_switch_rewrites_plan(
    client, db_session, monkeypatch
) -> None:
    """UAT S2: comic→single PATCH must not stamp format on a leftover 4-panel plan."""
    monkeypatch.setattr("internal.llm.router.has_llm_credentials", lambda: False)

    data = await register_user(client)
    headers = auth_header(data["access_token"])
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    session_id = await seed_preview_session(
        db_session, user_id=user_id, company_id=company_id
    )

    listed = await client.get(f"/api/sessions/{session_id}/media", headers=headers)
    image_id = listed.json()["media"][0]["id"]
    comic_plan = {
        "format": "comic_4panel",
        "prompt": (
            "4-panel comic strip for Acme, Hong Kong everyday scenes "
            "inspired by: seed, clear gutters, no logos"
        ),
        "composition": "2x2 comic grid, equal panels, reading L→R then top→bottom",
        "style": "clean line comic, contemporary HK urban",
        "panels": [
            {"index": 1, "beat": "hook"},
            {"index": 2, "beat": "friction"},
            {"index": 3, "beat": "peak"},
            {"index": 4, "beat": "remedy"},
        ],
    }
    comic = await client.patch(
        f"/api/sessions/{session_id}/media/{image_id}/plan",
        headers=headers,
        json={"plan": comic_plan},
    )
    assert comic.status_code == 200, comic.text
    comic_id = comic.json()["media"][0]["id"]
    assert comic.json()["media"][0]["format"] == "comic_4panel"
    assert len(comic.json()["media"][0]["plan"]["panels"]) == 4

    stamped = await client.patch(
        f"/api/sessions/{session_id}/media/{comic_id}/plan",
        headers=headers,
        json={"plan": {**comic.json()["media"][0]["plan"], "format": "single"}},
    )
    assert stamped.status_code == 200, stamped.text
    body = stamped.json()
    plan = body["media"][0]["plan"]
    assert body["media"][0]["format"] == "single"
    assert plan["format"] == "single"
    assert plan["panels"] == []
    assert "4-panel" not in plan["prompt"].lower()
    assert "2x2 comic" not in (plan.get("composition") or "").lower()

    db_session.expire_all()
    session = await db_session.get(Session, session_id)
    assert session is not None
    assert (session.state or {}).get("image_format") == "single"

    regen = await client.post(
        f"/api/sessions/{session_id}/media/{body['media'][0]['id']}/regen",
        headers=headers,
    )
    assert regen.status_code == 200, regen.text
    regen_plan = regen.json()["media"][0]["plan"]
    assert regen_plan["format"] == "single"
    assert regen_plan["panels"] == []
    assert "4-panel" not in regen_plan["prompt"].lower()
