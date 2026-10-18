"""Regression coverage for ADR 0047 review findings on PR #142.

- Download scope: ``session``/``user`` attachments are owner-only — company
  membership alone must not serve another member's file; ``org`` rows stay
  company-wide (the §3 owner matrix the retrieve path already enforces).
- Reachability: a session-scope ``attachment_sessions`` join row without a
  matching ``user_id`` must not satisfy ``PostMessageRequest.attachment_ids``
  — the matrix reads "this *member's* scratch on this session".
- ``content_type`` is derived server-side from the extension; an uploader
  cannot label bytes as ``text/html`` and have the download echo it on the
  application origin.
- Parked turns: a typed reply while image- or angle-parked keeps its
  ``attachment_ids`` on the persisted user row (ADR 0047 §8) instead of
  silently dropping them on the delegation path.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory import repos
from internal.memory.models import AttachmentSession, Session
from internal.session.graph import set_session_graph
from tests.api.attachment_helpers import (
    StubSessionGraph,
    make_offer_markdown,
    make_pdf_with_outline,
    none_embedder,
    patch_embedder,
    seed_pending_attachment,
)
from tests.api.helpers import auth_header, join_org, register_user

PDF_UPLOAD = ("catalog2026.pdf", make_pdf_with_outline(), "application/pdf")


async def _member_and_session(
    client: AsyncClient,
) -> tuple[dict, dict[str, str], uuid.UUID]:
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]
    res = await client.post("/api/sessions", json={"company_id": company_id}, headers=headers)
    assert res.status_code == 201, res.text
    return data, headers, uuid.UUID(res.json()["id"])


async def _upload(
    client: AsyncClient,
    session_id: uuid.UUID,
    headers: dict[str, str],
    *,
    filename: str,
    data: bytes,
    content_type: str,
) -> dict:
    res = await client.post(
        f"/api/sessions/{session_id}/attachments",
        files={"file": (filename, data, content_type)},
        headers=headers,
    )
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _add_company_member(
    client: AsyncClient, db_session: AsyncSession, company_id: uuid.UUID
) -> dict[str, str]:
    mate = await register_user(client)
    await join_org(
        db_session, user_id=uuid.UUID(mate["user"]["id"]), company_id=company_id, role="member"
    )
    return auth_header(mate["access_token"])


def _last_user_message(body: dict) -> dict:
    users = [m for m in body["messages"] if m["role"] == "user"]
    assert users, f"no user message in response: {body}"
    return users[-1]


# --- download owner matrix (SEC) ----------------------------------------------


@pytest.mark.asyncio
async def test_download_session_scratch_is_owner_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A colleague who knows a scratch attachment id must not download it —
    ``session`` scope is the uploader's alone (ADR 0047 §3 owner matrix)."""
    data, headers, session_id = await _member_and_session(client)
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    uploaded = await _upload(
        client,
        session_id,
        headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )
    attachment_id = uploaded["id"]

    mate_headers = await _add_company_member(client, db_session, company_id)
    res = await client.get(f"/api/attachments/{attachment_id}/download", headers=mate_headers)
    assert res.status_code == 404, res.text

    own = await client.get(f"/api/attachments/{attachment_id}/download", headers=headers)
    assert own.status_code == 200, own.text


@pytest.mark.asyncio
async def test_download_user_scope_is_owner_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A saved-to-library (``user`` scope) row is still the owner's alone."""
    data, headers, session_id = await _member_and_session(client)
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    uploaded = await _upload(
        client,
        session_id,
        headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )
    attachment_id = uploaded["id"]
    saved = await client.post(f"/api/attachments/{attachment_id}/save", headers=headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["owner_scope"] == "user"

    mate_headers = await _add_company_member(client, db_session, company_id)
    res = await client.get(f"/api/attachments/{attachment_id}/download", headers=mate_headers)
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_download_org_scope_stays_company_wide(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``org`` rows are company assets — a member other than the uploader
    (here: no uploader at all) still downloads."""
    data, _headers, _session_id = await _member_and_session(client)
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    attachment_id = await seed_pending_attachment(
        db_session,
        user_id=None,
        company_id=company_id,
        session_id=None,
        filename="menu.md",
        data=make_offer_markdown(),
        content_type="text/markdown",
        owner_scope="org",
    )
    mate_headers = await _add_company_member(client, db_session, company_id)
    res = await client.get(f"/api/attachments/{attachment_id}/download", headers=mate_headers)
    assert res.status_code == 200, res.text


# --- reachability via join row (SEC) -------------------------------------------


@pytest.mark.asyncio
async def test_message_join_row_for_other_members_scratch_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A session-scope ``attachment_sessions`` row alone must not satisfy
    reachability — the uploader's ``user_id`` has to match too. A dangling or
    wrongly-created cross-member join ref cannot hand a colleague the file."""
    victim, _victim_headers, _victim_session = await _member_and_session(client)
    company_id = uuid.UUID(victim["user"]["organizations"][0]["id"])
    attachment_id = await seed_pending_attachment(
        db_session,
        user_id=uuid.UUID(victim["user"]["id"]),
        company_id=company_id,
        session_id=None,
        filename="menu.md",
        data=make_offer_markdown(),
        content_type="text/markdown",
        owner_scope="session",
    )

    mate_headers = await _add_company_member(client, db_session, company_id)
    res = await client.post(
        "/api/sessions", json={"company_id": str(company_id)}, headers=mate_headers
    )
    assert res.status_code == 201, res.text
    attacker_session = uuid.UUID(res.json()["id"])

    # Simulates any path that left a join row pointing at another member's
    # scratch — reachability must still refuse (§14 uniform 404).
    db_session.add(AttachmentSession(attachment_id=attachment_id, session_id=attacker_session))
    await db_session.commit()

    posted = await client.post(
        f"/api/sessions/{attacker_session}/messages",
        json={"content": "睇吓呢份文件", "attachment_ids": [str(attachment_id)]},
        headers=mate_headers,
    )
    assert posted.status_code == 404, posted.text


# --- uploader-controlled content type (SEC) ------------------------------------


@pytest.mark.asyncio
async def test_upload_content_type_is_server_derived(client: AsyncClient) -> None:
    """The stored/echoed media type comes from the extension allowlist — an
    uploader cannot tag a payload ``text/html`` (stored-XSS surface)."""
    _data, headers, session_id = await _member_and_session(client)
    uploaded = await _upload(
        client,
        session_id,
        headers,
        filename="menu.pdf",
        data=PDF_UPLOAD[1],
        content_type="text/html",
    )
    assert uploaded["content_type"] == "application/pdf", uploaded

    res = await client.get(f"/api/attachments/{uploaded['id']}/download", headers=headers)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/pdf")
    assert "attachment" in res.headers.get("content-disposition", "")


# --- storage migration enumeration (BUG) ---------------------------------------


@pytest.mark.asyncio
async def test_media_ref_enumeration_includes_attachment_keys(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``list_all_media_refs`` feeds the local→S3 migration copy/verify sets —
    attachment object keys must be in it or the flip strands uploaded files."""
    from internal.memory import repos

    data, _headers, session_id = await _member_and_session(client)
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    attachment_id = await seed_pending_attachment(
        db_session,
        user_id=uuid.UUID(data["user"]["id"]),
        company_id=company_id,
        session_id=session_id,
        filename="menu.md",
        data=make_offer_markdown(),
        content_type="text/markdown",
    )

    refs = await repos.list_all_media_refs(db_session)
    assert f"attachments/{attachment_id}/menu.md" in refs


# --- parked turns keep attachment refs (BUG) ------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_overlong_filename(client: AsyncClient) -> None:
    """A filename whose UTF-8 bytes exceed the cap is refused up front —
    local stores cap path components at 255 bytes, and migration enumeration
    must never see a key it can't classify."""
    _data, headers, session_id = await _member_and_session(client)
    res = await client.post(
        f"/api/sessions/{session_id}/attachments",
        files={"file": ("a" * 250 + ".pdf", PDF_UPLOAD[1], "application/pdf")},
        headers=headers,
    )
    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_parked_image_reply_keeps_attachment_refs(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0036: a typed reply while image-parked is a new script turn — its
    attachment_ids must ride along instead of silently dropping (§8)."""
    patch_embedder(monkeypatch, none_embedder)
    set_session_graph(StubSessionGraph(reply="收到"))
    _data, headers, session_id = await _member_and_session(client)
    uploaded = await _upload(
        client,
        session_id,
        headers,
        filename="offers.md",
        data=make_offer_markdown(),
        content_type="text/markdown",
    )
    attachment_id = uploaded["id"]

    session = await db_session.get(Session, session_id)
    assert session is not None
    session.state = {**(session.state or {}), "awaiting_image_ok": True}
    await db_session.commit()

    posted = await client.post(
        f"/api/sessions/{session_id}/messages",
        json={
            "content": "標題改成紅色",
            "attachment_ids": [attachment_id],
        },
        headers=headers,
    )
    assert posted.status_code == 200, posted.text
    msg = _last_user_message(posted.json())
    assert attachment_id in (msg.get("metadata") or {}).get("attachment_ids", [])
    chips = {str(d.get("id")) for d in msg.get("attachments") or []}
    assert attachment_id in chips, f"no digest chip on parked-reply message: {msg}"


@pytest.mark.asyncio
async def test_retried_angle_pick_merges_attachment_refs(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Idempotent-retry edge: the first typed pick already persisted a user
    row with no refs; a retry carrying ``attachment_ids`` must merge them
    onto that row (chips + digests), not drop them with the skip."""
    patch_embedder(monkeypatch, none_embedder)
    set_session_graph(StubSessionGraph(reply="好"))
    _data, headers, session_id = await _member_and_session(client)
    uploaded = await _upload(
        client,
        session_id,
        headers,
        filename="offers.md",
        data=make_offer_markdown(),
        content_type="text/markdown",
    )
    attachment_id = uploaded["id"]

    session = await db_session.get(Session, session_id)
    assert session is not None
    session.state = {
        **(session.state or {}),
        "awaiting_angle_pick": True,
        "brief": {"angles": ["慳錢角度", "打卡角度"]},
    }
    # Simulates the earlier failed pick attempt that persisted its user row.
    pick_text = "用打卡角度"
    await repos.add_session_message(
        db_session, session_id=session_id, role="user", content=pick_text
    )
    await db_session.commit()

    posted = await client.post(
        f"/api/sessions/{session_id}/messages",
        json={"content": pick_text, "attachment_ids": [attachment_id]},
        headers=headers,
    )
    assert posted.status_code == 200, posted.text
    msg = _last_user_message(posted.json())
    assert attachment_id in (msg.get("metadata") or {}).get("attachment_ids", []), msg
    chips = {str(d.get("id")) for d in msg.get("attachments") or []}
    assert attachment_id in chips, f"no digest chip on retried pick: {msg}"


@pytest.mark.asyncio
async def test_parked_angle_reply_keeps_attachment_refs(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0028: a typed reply while angle-parked is the pick — the row it
    persists must keep its attachment_ids + digest chips (§8)."""
    patch_embedder(monkeypatch, none_embedder)
    set_session_graph(StubSessionGraph(reply="好"))
    _data, headers, session_id = await _member_and_session(client)
    uploaded = await _upload(
        client,
        session_id,
        headers,
        filename="offers.md",
        data=make_offer_markdown(),
        content_type="text/markdown",
    )
    attachment_id = uploaded["id"]

    session = await db_session.get(Session, session_id)
    assert session is not None
    session.state = {
        **(session.state or {}),
        "awaiting_angle_pick": True,
        "brief": {"angles": ["慳錢角度", "打卡角度"]},
    }
    await db_session.commit()

    posted = await client.post(
        f"/api/sessions/{session_id}/messages",
        json={
            "content": "用打卡角度",
            "attachment_ids": [attachment_id],
        },
        headers=headers,
    )
    assert posted.status_code == 200, posted.text
    msg = _last_user_message(posted.json())
    assert attachment_id in (msg.get("metadata") or {}).get("attachment_ids", [])
    chips = {str(d.get("id")) for d in msg.get("attachments") or []}
    assert attachment_id in chips, f"no digest chip on parked-reply message: {msg}"
