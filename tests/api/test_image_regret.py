"""ADR 0036: a direction change writes a new script and plan before Execute."""

from __future__ import annotations

import uuid

import pytest

from internal.memory import repos
from internal.memory.models import Session
from internal.session import nodes as N
from internal.session.graph import set_session_graph
from tests.api.helpers import auth_header, register_user, seed_preview_session

DIRECTION = "唔要黃色雨傘，改成藍色天空"


async def _passing_reviewer(state: dict) -> dict:
    return {
        "reviewer_passed": True,
        "reviewer_feedback": "",
        "review_attempts": int(state.get("review_attempts") or 0),
    }


async def _skip_research(_state: dict) -> dict:
    return {"research_rule_pass": False, "research": {"need_facts": False}}


@pytest.mark.asyncio
async def test_chat_direction_change_stages_script_then_execute(
    client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(N, "has_llm_credentials", lambda: False)
    monkeypatch.setattr("internal.llm.router.has_llm_credentials", lambda: False)
    monkeypatch.setattr(N, "reviewer", _passing_reviewer)
    monkeypatch.setattr(N, "fast_rule_checker", _skip_research)
    set_session_graph(None)

    data = await register_user(client)
    headers = auth_header(data["access_token"])
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    session_id = await seed_preview_session(
        db_session, user_id=user_id, company_id=company_id
    )

    try:
        posted = await client.post(
            f"/api/sessions/{session_id}/messages",
            headers=headers,
            json={"content": DIRECTION},
        )
        assert posted.status_code == 200, posted.text
        body = posted.json()
        assert body["interrupted"] is True
        preview = next(ev for ev in body["events"] if ev["type"] == "preview.updated")
        assert "藍色天空" in preview["data"]["copy"]["caption"]
        assert preview["data"]["revision"] >= 2

        db_session.expire_all()
        draft = await repos.get_latest_preview_draft(db_session, session_id)
        assert draft is not None
        pending_revision = draft.revision
        assert "藍色天空" in (draft.copy or {}).get("caption", "")
        assert draft.image_plan
        session = await db_session.get(Session, session_id)
        assert session is not None
        assert (session.state or {}).get("awaiting_image_ok") is True

        hydrated = await client.get(
            f"/api/sessions/{session_id}/messages", headers=headers
        )
        assert hydrated.status_code == 200, hydrated.text
        assert hydrated.json()["awaiting_image_ok"] is True
        assert hydrated.json()["recommended_image_format"] == "single"

        mismatch = await client.post(
            f"/api/sessions/{session_id}/resume-image",
            headers=headers,
            json={"image_format": "comic_4panel"},
        )
        assert mismatch.status_code == 400, mismatch.text

        db_session.expire_all()
        still = await repos.get_latest_preview_draft(db_session, session_id)
        assert still is not None
        assert "藍色天空" in (still.copy or {}).get("caption", "")

        executed = await client.post(
            f"/api/sessions/{session_id}/resume-image",
            headers=headers,
            json={},
        )
        assert executed.status_code == 200, executed.text
        done = executed.json()
        assert done["interrupted"] is False
        preview_done = next(
            ev for ev in done["events"] if ev["type"] == "preview.updated"
        )
        assert "藍色天空" in preview_done["data"]["copy"]["caption"]
        assert preview_done["data"]["image_url"]

        db_session.expire_all()
        final = await repos.get_latest_preview_draft(db_session, session_id)
        assert final is not None
        assert final.revision > pending_revision
        assert "藍色天空" in (final.copy or {}).get("caption", "")
        assert final.image_url
    finally:
        set_session_graph(None)


@pytest.mark.asyncio
async def test_discard_pending_direction_restores_accepted_caption(
    client, db_session, monkeypatch
) -> None:
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
    patched = await client.patch(
        f"/api/sessions/{session_id}/media/{image_id}/plan",
        headers=headers,
        json={
            "plan": {
                "prompt": "blue sky, no yellow umbrella",
                "format": "single",
                "style": "clean",
            }
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["awaiting_image_ok"] is True
    assert "blue sky" in patched.json()["copy"]["caption"]

    db_session.expire_all()
    pending = await repos.get_latest_preview_draft(db_session, session_id)
    assert pending is not None
    assert pending.revision == 2
    assert "blue sky" in (pending.copy or {}).get("caption", "")

    stopped = await client.post(f"/api/sessions/{session_id}/stop", headers=headers)
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "cancelled"

    db_session.expire_all()
    restored = await repos.get_latest_preview_draft(db_session, session_id)
    assert restored is not None
    assert restored.revision == 1
    assert (restored.copy or {}).get("caption") == "seed"


@pytest.mark.asyncio
async def test_edit_format_change_then_execute(client, db_session, monkeypatch) -> None:
    monkeypatch.setattr("internal.llm.router.has_llm_credentials", lambda: False)
    monkeypatch.setattr(N, "has_llm_credentials", lambda: False)
    set_session_graph(None)

    data = await register_user(client)
    headers = auth_header(data["access_token"])
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    session_id = await seed_preview_session(
        db_session, user_id=user_id, company_id=company_id
    )

    try:
        listed = await client.get(f"/api/sessions/{session_id}/media", headers=headers)
        image_id = listed.json()["media"][0]["id"]
        comic = await client.patch(
            f"/api/sessions/{session_id}/media/{image_id}/plan",
            headers=headers,
            json={
                "plan": {
                    "format": "comic_4panel",
                    "prompt": "4-panel comic about a blue sky",
                    "composition": "2x2 comic grid",
                    "style": "clean line comic",
                    "panels": [
                        {"index": 1, "beat": "hook"},
                        {"index": 2, "beat": "friction"},
                        {"index": 3, "beat": "peak"},
                        {"index": 4, "beat": "remedy"},
                    ],
                }
            },
        )
        assert comic.status_code == 200, comic.text
        body = comic.json()
        assert body["awaiting_image_ok"] is True
        assert "4格漫畫" in body["copy"]["caption"]
        assert body["media"][0]["format"] == "comic_4panel"

        db_session.expire_all()
        pending = await repos.get_latest_preview_draft(db_session, session_id)
        assert pending is not None
        assert "4格漫畫" in (pending.copy or {}).get("caption", "")

        executed = await client.post(
            f"/api/sessions/{session_id}/resume-image",
            headers=headers,
            json={"image_format": "comic_4panel"},
        )
        assert executed.status_code == 200, executed.text
        done = executed.json()
        assert done["interrupted"] is False
        preview = next(ev for ev in done["events"] if ev["type"] == "preview.updated")
        assert "4格漫畫" in preview["data"]["copy"]["caption"]
        assert preview["data"]["image_url"]
    finally:
        set_session_graph(None)
