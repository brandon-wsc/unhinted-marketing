"""API-tier tests for the ADR 0047 session-wiring step.

Covers §3 (``PostMessageRequest.attachment_ids`` validation + message
reference + digest hydration), §2 (save-to-library is HTTP), §13
(``attachment_sessions`` join, fork share-by-ref, last-session GC) and the
Consequences row (``attachments[]`` on ``SessionState`` + ``MessageResponse``).

Pinned contract — invented names this step must satisfy:

- ``PostMessageRequest.attachment_ids: list[uuid.UUID]`` — every id is
  validated server-side (§14): this session's scratch (``attachment_sessions``
  join or ``session_id``) or the member's ``user``/``org`` library
  (``owner_scope=user`` + ``user_id`` match, ``owner_scope=org`` + company
  match — the ``document_retrieve._visible_to_member`` matrix). Unknown,
  cross-tenant, other-session scratch and another member's scratch ids all
  get **404** (chosen code — identical to the ADR's cross-tenant 404 so
  existence never leaks). A member's scratch on *another* of their sessions
  is also 404 — §3 reads "this session's scratch".
- The persisted user message stores ``metadata["attachment_ids"]`` as uuid
  strings (``MESSAGE_ATTACHMENT_IDS_KEY``); ``MessageResponse.attachments``
  carries digest chips ``[{id, filename, status}]``
  (``MESSAGE_ATTACHMENTS_FIELD``).
- ``session.state["attachments"]`` holds hydrated digests
  ``{id, filename, status, doc_profile subset}`` per §5/§13 — any of
  ``DIGEST_PROFILE_KEYS`` satisfies the "doc_profile subset" leg.
- ``POST /api/attachments/{id}/save`` (``SAVE_ATTACHMENT_PATH``) — the §2
  HTTP save-to-library action: flips the caller's own session-scratch row to
  ``owner_scope="user"`` and returns the updated ``AttachmentOut``. Unknown /
  cross-company / non-owner (same-company member on another member's
  scratch) → 404; re-saving an already-user-scope row → 200 (idempotent —
  chosen over 4xx). Org-scope save is unpinned and untested.
- Session delete GC (§13): deleting a session reclaims scratch attachment
  rows + ``document_chunks`` + ``attachment_sessions`` rows + object bytes
  when its ``attachment_sessions`` row was the last reference. Saved
  (user-scope) rows and their bytes survive. ``POST /sessions/{id}/fork``
  copies join rows for attachments referenced by copied messages, so a fork
  keeps the file alive.
- Chat never commits (§2 / ADR 0011): a save-phrase message turn cannot
  produce an ``owner_scope="user"`` row.

The turn runs against ``StubSessionGraph`` (``set_session_graph``) — a
deterministic echo graph needing no LLM keys; ``clean_db`` resets it per
test. Everything pinned above is unimplemented today, so these tests fail on
the missing field/route/behavior — never on collection errors.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from internal.media.storage import MediaStorageError, get_bytes
from internal.memory.models import Attachment
from internal.session.graph import set_session_graph
from tests.api.attachment_helpers import (
    DIGEST_PROFILE_KEYS,
    MESSAGE_ATTACHMENT_IDS_KEY,
    MESSAGE_ATTACHMENTS_FIELD,
    SAVE_ATTACHMENT_PATH,
    STATE_ATTACHMENTS_KEY,
    StubSessionGraph,
    fetch_attachment_or_none,
    fetch_chunk_count,
    fetch_join_rows,
    fetch_session_row,
    list_attachment_rows,
    make_offer_markdown,
    make_pdf_with_outline,
    make_scanned_pdf,
    none_embedder,
    patch_embedder,
    read_object_bytes,
    run_next_pending_job,
    seed_pending_attachment,
)
from tests.api.helpers import auth_header, join_org, register_user

PROSE_UPLOAD = ("offers.md", make_offer_markdown(), "text/markdown")
PDF_UPLOAD = ("catalog2026.pdf", make_pdf_with_outline(), "application/pdf")


# --- local helpers ------------------------------------------------------------


async def _member_and_session(
    client: AsyncClient,
) -> tuple[dict, dict[str, str], uuid.UUID]:
    """Register a user and create a session via the real routes."""
    data = await register_user(client)
    headers = auth_header(data["access_token"])
    company_id = data["user"]["organizations"][0]["id"]
    res = await client.post("/api/sessions", json={"company_id": company_id}, headers=headers)
    assert res.status_code == 201, res.text
    return data, headers, uuid.UUID(res.json()["id"])


async def _new_session(client: AsyncClient, headers: dict[str, str], company_id: str) -> uuid.UUID:
    res = await client.post("/api/sessions", json={"company_id": company_id}, headers=headers)
    assert res.status_code == 201, res.text
    return uuid.UUID(res.json()["id"])


async def _upload(
    client: AsyncClient,
    session_id: uuid.UUID,
    headers: dict[str, str],
    *,
    filename: str,
    data: bytes,
    content_type: str,
) -> uuid.UUID:
    res = await client.post(
        f"/api/sessions/{session_id}/attachments",
        files={"file": (filename, data, content_type)},
        headers=headers,
    )
    assert res.status_code in (200, 201), res.text
    return uuid.UUID(res.json()["id"])


async def _drain_attachment_jobs(limit: int = 8) -> None:
    """Run queued attachment jobs synchronously (ingest → optional embed)."""
    for _ in range(limit):
        if await run_next_pending_job() is None:
            return
    raise AssertionError("attachment job queue did not drain")


async def _post_message(
    client: AsyncClient,
    session_id: uuid.UUID,
    headers: dict[str, str],
    *,
    content: str,
    attachment_ids: list[uuid.UUID] | None = None,
) -> Response:
    payload: dict = {"content": content}
    if attachment_ids is not None:
        payload["attachment_ids"] = [str(i) for i in attachment_ids]
    return await client.post(f"/api/sessions/{session_id}/messages", json=payload, headers=headers)


def _last_user_message(body: dict) -> dict:
    users = [m for m in body["messages"] if m["role"] == "user"]
    assert users, f"no user message in response: {body}"
    return users[-1]


def _message_attachment_ids(msg: dict) -> list[str]:
    return [str(i) for i in ((msg.get("metadata") or {}).get(MESSAGE_ATTACHMENT_IDS_KEY) or [])]


def _digest_for(msg: dict, attachment_id: uuid.UUID) -> dict | None:
    for d in msg.get(MESSAGE_ATTACHMENTS_FIELD) or []:
        if str(d.get("id")) == str(attachment_id):
            return d
    return None


def _assert_message_reference(msg: dict, attachment_id: uuid.UUID) -> dict:
    """The user message stores the id list AND carries the digest chip."""
    assert str(attachment_id) in _message_attachment_ids(msg), (
        f"user message metadata lacks {MESSAGE_ATTACHMENT_IDS_KEY}: {msg}"
    )
    digest = _digest_for(msg, attachment_id)
    assert digest is not None, f"no attachment digest on message: {msg}"
    assert digest.get("filename")
    assert digest.get("status")
    return digest


async def _state_digest(session_id: uuid.UUID, attachment_id: uuid.UUID) -> dict | None:
    session = await fetch_session_row(session_id)
    assert session is not None
    digests = (session.state or {}).get(STATE_ATTACHMENTS_KEY) or []
    return next((d for d in digests if str(d.get("id")) == str(attachment_id)), None)


def _save_path(attachment_id: uuid.UUID) -> str:
    return SAVE_ATTACHMENT_PATH.format(attachment_id=attachment_id)


# --- POST /messages attachment_ids ----------------------------------------------


@pytest.mark.asyncio
async def test_post_message_with_session_attachment_carries_reference_and_digest(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path (§3/§5): attach this session's scratch file — the user
    message stores the reference, MessageResponse carries the digest chip,
    and session.state gains the hydrated digest."""
    patch_embedder(monkeypatch, none_embedder)  # ingest lands ready_lexical
    _data, headers, session_id = await _member_and_session(client)
    filename, data, content_type = PROSE_UPLOAD
    attachment_id = await _upload(
        client,
        session_id,
        headers,
        filename=filename,
        data=data,
        content_type=content_type,
    )
    await _drain_attachment_jobs()
    set_session_graph(StubSessionGraph())

    res = await _post_message(
        client,
        session_id,
        headers,
        content="用呢份嘢出個 post",
        attachment_ids=[attachment_id],
    )
    assert res.status_code == 200, res.text

    digest = _assert_message_reference(_last_user_message(res.json()), attachment_id)
    assert digest["filename"] == filename

    state_digest = await _state_digest(session_id, attachment_id)
    assert state_digest is not None, "session.state lacks the hydrated attachment digest"
    assert state_digest.get("filename") == filename
    assert state_digest.get("status") in {"ready_lexical", "ready"}
    assert any(k in state_digest for k in DIGEST_PROFILE_KEYS), (
        f"digest misses the doc_profile subset: {state_digest}"
    )


@pytest.mark.asyncio
async def test_post_message_unknown_attachment_id_is_404(
    client: AsyncClient,
) -> None:
    _data, headers, session_id = await _member_and_session(client)
    set_session_graph(StubSessionGraph())

    res = await _post_message(
        client,
        session_id,
        headers,
        content="用呢份嘢出個 post",
        attachment_ids=[uuid.uuid4()],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_post_message_other_company_attachment_is_404(
    client: AsyncClient,
) -> None:
    """Cross-tenant ids → 404 (§3): another company's session scratch."""
    _data, headers, session_id = await _member_and_session(client)
    other = await register_user(client)
    other_headers = auth_header(other["access_token"])
    other_session = await _new_session(
        client, other_headers, other["user"]["organizations"][0]["id"]
    )
    foreign = await _upload(
        client,
        other_session,
        other_headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )
    set_session_graph(StubSessionGraph())

    res = await _post_message(
        client,
        session_id,
        headers,
        content="用呢份嘢出個 post",
        attachment_ids=[foreign],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_post_message_other_members_session_scratch_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Scratch belongs to its session — a same-company teammate's session
    scratch is not attachable (§3 'this session's scratch')."""
    data, headers, session_id = await _member_and_session(client)
    company_id = data["user"]["organizations"][0]["id"]
    mate = await register_user(client)
    await join_org(
        db_session,
        user_id=uuid.UUID(mate["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    mate_headers = auth_header(mate["access_token"])
    mate_session = await _new_session(client, mate_headers, company_id)
    mate_attachment = await _upload(
        client,
        mate_session,
        mate_headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )
    set_session_graph(StubSessionGraph())

    res = await _post_message(
        client,
        session_id,
        headers,
        content="用呢份嘢出個 post",
        attachment_ids=[mate_attachment],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_post_message_scratch_from_members_other_session_is_404(
    client: AsyncClient,
) -> None:
    """Chosen reading of §3: scratch validates against *this* session only —
    the member's own scratch on another session is 404, not a library row."""
    _data, headers, session_id = await _member_and_session(client)
    company_id = _data["user"]["organizations"][0]["id"]
    other_session = await _new_session(client, headers, company_id)
    other_attachment = await _upload(
        client,
        other_session,
        headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )
    set_session_graph(StubSessionGraph())

    res = await _post_message(
        client,
        session_id,
        headers,
        content="用呢份嘢出個 post",
        attachment_ids=[other_attachment],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["user", "org"], ids=["user", "org"])
async def test_post_message_accepts_member_library_attachment(
    client: AsyncClient, db_session: AsyncSession, scope: str
) -> None:
    """§3 library attach works cross-session: the member's own ``user`` row
    or any ``org`` row of their company attaches without an upload."""
    data, headers, session_id = await _member_and_session(client)
    attachment_id = await seed_pending_attachment(
        db_session,
        user_id=uuid.UUID(data["user"]["id"]) if scope == "user" else None,
        company_id=uuid.UUID(data["user"]["organizations"][0]["id"]),
        session_id=None,
        filename="library.md",
        data=b"# library doc\n\nbody text",
        content_type="text/markdown",
        owner_scope=scope,
    )
    set_session_graph(StubSessionGraph())

    res = await _post_message(
        client,
        session_id,
        headers,
        content="用我庫入面嗰份嘢出個 post",
        attachment_ids=[attachment_id],
    )
    assert res.status_code == 200, res.text
    _assert_message_reference(_last_user_message(res.json()), attachment_id)


# --- save to library (HTTP, §2) --------------------------------------------------


@pytest.mark.asyncio
async def test_save_attachment_flips_scratch_to_user_scope(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    data, headers, session_id = await _member_and_session(client)
    attachment_id = await _upload(
        client,
        session_id,
        headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )

    res = await client.post(_save_path(attachment_id), headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == str(attachment_id)
    assert body["owner_scope"] == "user"

    row = await db_session.get(Attachment, attachment_id)
    assert row is not None
    assert row.owner_scope == "user"
    assert row.user_id == uuid.UUID(data["user"]["id"])


@pytest.mark.asyncio
async def test_save_attachment_is_idempotent(client: AsyncClient) -> None:
    """Re-saving an already-user-scope row → 200, still the member's doc."""
    _data, headers, session_id = await _member_and_session(client)
    attachment_id = await _upload(
        client,
        session_id,
        headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )
    first = await client.post(_save_path(attachment_id), headers=headers)
    assert first.status_code == 200, first.text
    second = await client.post(_save_path(attachment_id), headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["owner_scope"] == "user"


@pytest.mark.asyncio
async def test_save_attachment_unknown_id_is_404(client: AsyncClient) -> None:
    """Route-missing is also 404 — save a real attachment first so a missing
    route cannot pass as a refusal."""
    _data, headers, session_id = await _member_and_session(client)
    attachment_id = await _upload(
        client,
        session_id,
        headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )
    own = await client.post(_save_path(attachment_id), headers=headers)
    assert own.status_code == 200, own.text

    res = await client.post(_save_path(uuid.uuid4()), headers=headers)
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_save_attachment_cross_company_is_404(client: AsyncClient) -> None:
    _data, headers, session_id = await _member_and_session(client)
    attachment_id = await _upload(
        client,
        session_id,
        headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )
    own = await client.post(_save_path(attachment_id), headers=headers)
    assert own.status_code == 200, own.text

    outsider = await register_user(client)
    res = await client.post(
        _save_path(attachment_id), headers=auth_header(outsider["access_token"])
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_save_attachment_other_member_same_company_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Owner-only: a same-company member cannot save another member's
    session-scratch row (§2 — Mine means *my* upload). The owner saves a
    *second* scratch row first so a missing route cannot pass as a refusal;
    the contested row stays session-scoped for the member's attempt."""
    data, headers, session_id = await _member_and_session(client)
    attachment_id = await _upload(
        client,
        session_id,
        headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )
    other_id = await _upload(
        client,
        session_id,
        headers,
        filename="offers.md",
        data=make_offer_markdown(),
        content_type="text/markdown",
    )
    own = await client.post(_save_path(other_id), headers=headers)
    assert own.status_code == 200, own.text

    mate = await register_user(client)
    await join_org(
        db_session,
        user_id=uuid.UUID(mate["user"]["id"]),
        company_id=uuid.UUID(data["user"]["organizations"][0]["id"]),
        role="member",
    )
    res = await client.post(_save_path(attachment_id), headers=auth_header(mate["access_token"]))
    assert res.status_code == 404, res.text


# --- session delete GC (§13) -----------------------------------------------------


@pytest.mark.asyncio
async def test_delete_session_reclaims_scratch_attachment(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scratch dies with the last referencing session: attachment row,
    document_chunks, attachment_sessions join and object bytes all go."""
    patch_embedder(monkeypatch, none_embedder)
    _data, headers, session_id = await _member_and_session(client)
    filename, data, content_type = PROSE_UPLOAD
    attachment_id = await _upload(
        client,
        session_id,
        headers,
        filename=filename,
        data=data,
        content_type=content_type,
    )
    await _drain_attachment_jobs()  # chunks exist under ready_lexical

    row = await db_session.get(Attachment, attachment_id)
    assert row is not None
    object_key = row.object_key
    assert await fetch_chunk_count(attachment_id) > 0
    assert await get_bytes(object_key) == data

    res = await client.delete(f"/api/sessions/{session_id}", headers=headers)
    assert res.status_code == 204, res.text

    assert await fetch_attachment_or_none(attachment_id) is None
    assert await fetch_chunk_count(attachment_id) == 0
    assert await fetch_join_rows(attachment_id) == []
    with pytest.raises(MediaStorageError):
        await get_bytes(object_key)


@pytest.mark.asyncio
async def test_delete_session_keeps_saved_attachment(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A saved (user-scope) attachment is library, not scratch — the row and
    its bytes survive the session it was uploaded into."""
    data, headers, session_id = await _member_and_session(client)
    filename, content, content_type = PDF_UPLOAD
    attachment_id = await _upload(
        client,
        session_id,
        headers,
        filename=filename,
        data=content,
        content_type=content_type,
    )
    row = await db_session.get(Attachment, attachment_id)
    assert row is not None
    object_key = row.object_key

    saved = await client.post(_save_path(attachment_id), headers=headers)
    assert saved.status_code == 200, saved.text

    res = await client.delete(f"/api/sessions/{session_id}", headers=headers)
    assert res.status_code == 204, res.text

    kept = await fetch_attachment_or_none(attachment_id)
    assert kept is not None
    assert kept.owner_scope == "user"
    assert kept.user_id == uuid.UUID(data["user"]["id"])
    assert await read_object_bytes(object_key) == content


@pytest.mark.asyncio
async def test_forked_session_shares_attachment_by_reference(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ADR 0047 §13: fork inserts attachment_sessions rows for attachments
    referenced by copied messages; GC waits for the last referencing session."""
    _data, headers, session_id = await _member_and_session(client)
    filename, content, content_type = PDF_UPLOAD
    attachment_id = await _upload(
        client,
        session_id,
        headers,
        filename=filename,
        data=content,
        content_type=content_type,
    )
    row = await db_session.get(Attachment, attachment_id)
    assert row is not None
    object_key = row.object_key

    set_session_graph(StubSessionGraph())
    res = await _post_message(
        client,
        session_id,
        headers,
        content="用呢份嘢出個 post",
        attachment_ids=[attachment_id],
    )
    assert res.status_code == 200, res.text
    msg = _last_user_message(res.json())
    _assert_message_reference(msg, attachment_id)

    fork = await client.post(
        f"/api/sessions/{session_id}/fork",
        json={"message_id": msg["id"]},
        headers=headers,
    )
    assert fork.status_code == 201, fork.text
    fork_id = uuid.UUID(fork.json()["session"]["id"])

    # The fork references the same attachment — join row must exist so
    # digests keep hydrating and GC knows it is shared.
    assert await fetch_join_rows(attachment_id, session_id=fork_id), (
        "fork did not record an attachment_sessions row"
    )

    res = await client.delete(f"/api/sessions/{session_id}", headers=headers)
    assert res.status_code == 204, res.text
    surviving = await fetch_attachment_or_none(attachment_id)
    assert surviving is not None, "fork still references — row must survive"
    assert await read_object_bytes(object_key) == content

    res = await client.delete(f"/api/sessions/{fork_id}", headers=headers)
    assert res.status_code == 204, res.text
    assert await fetch_attachment_or_none(attachment_id) is None
    assert await fetch_join_rows(attachment_id) == []
    assert await read_object_bytes(object_key) is None


# --- chat never commits ----------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_phrase_cannot_save_attachment(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """「幫我存入我嘅庫」is a chat phrase, not a commit: the turn may do
    anything, but no ``owner_scope="user"`` row may appear (§2 — save is
    HTTP-only)."""
    data, headers, session_id = await _member_and_session(client)
    attachment_id = await _upload(
        client,
        session_id,
        headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )
    set_session_graph(StubSessionGraph(reply="想儲起佢？撳「存入我嘅庫」啦。"))

    res = await _post_message(
        client,
        session_id,
        headers,
        content="幫我存入我嘅庫",
        attachment_ids=[attachment_id],
    )
    assert res.status_code == 200, res.text
    # The phrase rides a real attachment reference (fails until
    # attachment_ids lands)…
    _assert_message_reference(_last_user_message(res.json()), attachment_id)
    # …but chat never commits: the scratch row stays session-scoped and no
    # user-scope row materializes for the member.
    row = await fetch_attachment_or_none(attachment_id)
    assert row is not None and row.owner_scope == "session"
    saved = await list_attachment_rows(user_id=uuid.UUID(data["user"]["id"]), owner_scope="user")
    assert saved == []


# --- review-fix additions (ADR 0047 Consequences + §8) -----------------------------
#
# The two-axis UI review found the contract gaps below. ``GET
# /api/sessions/{id}/attachments`` (Consequences: "POST/GET …/attachments")
# is the only wire-level way for the UI to observe ingest status, the
# readable ``error`` text (§10) and the ``doc_profile`` digest (§5) —
# until now every one of those assertions had to read the DB row.
# ``PostMessageRequest.content`` also needs to relax for a true
# attachment-only message (§8 zero-instruction upload).


@pytest.mark.asyncio
async def test_get_session_attachments_lists_upload_with_status(
    client: AsyncClient,
) -> None:
    """Consequences row: GET …/attachments returns this session's rows."""
    _data, headers, session_id = await _member_and_session(client)
    attachment_id = await _upload(
        client,
        session_id,
        headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )

    res = await client.get(f"/api/sessions/{session_id}/attachments", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    items = body["attachments"] if isinstance(body, dict) else body
    match = next((a for a in items if a["id"] == str(attachment_id)), None)
    assert match is not None, f"uploaded attachment missing from list: {items}"
    assert match["filename"] == PDF_UPLOAD[0]
    assert match["status"] in {"pending", "ready_lexical", "ready", "failed"}
    assert match["owner_scope"] == "session"


@pytest.mark.asyncio
async def test_get_session_attachments_surfaces_error_and_profile(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§10 'the attachment tells the truth' needs the error on the wire:
    a failed ingest's row carries non-empty ``error``; a successful one
    carries the §5 ``doc_profile`` digest."""
    patch_embedder(monkeypatch, none_embedder)
    _data, headers, session_id = await _member_and_session(client)
    bad_id = await _upload(
        client,
        session_id,
        headers,
        filename="scan.pdf",
        data=make_scanned_pdf(),
        content_type="application/pdf",
    )
    good_id = await _upload(
        client,
        session_id,
        headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )
    await _drain_attachment_jobs()

    res = await client.get(f"/api/sessions/{session_id}/attachments", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    items = body["attachments"] if isinstance(body, dict) else body
    by_id = {a["id"]: a for a in items}
    bad = by_id[str(bad_id)]
    assert bad["status"] == "failed"
    assert bad["error"], f"failed row lacks readable error: {bad}"
    good = by_id[str(good_id)]
    assert good["status"] == "ready_lexical"
    assert (good["doc_profile"] or {}).get("title")


@pytest.mark.asyncio
async def test_get_session_attachments_requires_owner(client: AsyncClient) -> None:
    _data, _headers, session_id = await _member_and_session(client)
    other = await register_user(client)
    res = await client.get(
        f"/api/sessions/{session_id}/attachments",
        headers=auth_header(other["access_token"]),
    )
    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_post_message_attachment_only_content(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8 zero-instruction upload: a message may carry only the attachment —
    empty ``content`` is valid when ``attachment_ids`` is non-empty."""
    patch_embedder(monkeypatch, none_embedder)
    _data, headers, session_id = await _member_and_session(client)
    attachment_id = await _upload(
        client,
        session_id,
        headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )
    await _drain_attachment_jobs()
    set_session_graph(StubSessionGraph())

    res = await client.post(
        f"/api/sessions/{session_id}/messages",
        json={"content": "", "attachment_ids": [str(attachment_id)]},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    _assert_message_reference(_last_user_message(res.json()), attachment_id)


@pytest.mark.asyncio
async def test_post_message_empty_content_still_422(client: AsyncClient) -> None:
    """Empty content without attachments stays invalid."""
    _data, headers, session_id = await _member_and_session(client)
    res = await client.post(
        f"/api/sessions/{session_id}/messages",
        json={"content": ""},
        headers=headers,
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_message_chip_carries_title(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8: the reply/digest quotes the doc title — the chip must ship it."""
    patch_embedder(monkeypatch, none_embedder)
    _data, headers, session_id = await _member_and_session(client)
    attachment_id = await _upload(
        client,
        session_id,
        headers,
        filename=PDF_UPLOAD[0],
        data=PDF_UPLOAD[1],
        content_type=PDF_UPLOAD[2],
    )
    await _drain_attachment_jobs()
    set_session_graph(StubSessionGraph())

    res = await _post_message(
        client,
        session_id,
        headers,
        content="呢份係咩嚟",
        attachment_ids=[attachment_id],
    )
    assert res.status_code == 200, res.text
    digest = _assert_message_reference(_last_user_message(res.json()), attachment_id)
    assert digest.get("title"), f"chip lacks doc title: {digest}"
