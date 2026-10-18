"""Step defs for the ADR 0047 ingest-job + upload scenarios in attachments.feature.

Uploads POST real multipart bytes to ``POST /api/sessions/{id}/attachments``
and drain the ADR 0039 job queue synchronously. Slice retrieval, library and
GC scenarios land in later steps and bind in their own modules, so this file
uses ``scenario()`` per scenario rather than ``scenarios()`` on the feature.
Steps stay sync (pytest-bdd); async work goes through ``api.run``.
"""

from __future__ import annotations

import uuid

from pytest_bdd import given, parsers, scenario, then, when

from internal.memory.document_chunk import ChunkConfig
from internal.session.graph import set_session_graph
from tests.api.attachment_helpers import (
    DIGEST_PROFILE_KEYS,
    MESSAGE_ATTACHMENT_IDS_KEY,
    MESSAGE_ATTACHMENTS_FIELD,
    SAVE_ATTACHMENT_PATH,
    STATE_ATTACHMENTS_KEY,
    StubSessionGraph,
    fetch_attachment_or_none,
    fetch_attachment_row,
    fetch_chunk_count,
    fetch_chunk_rows,
    fetch_join_rows,
    fetch_session_row,
    list_attachment_rows,
    make_digest_probe_model,
    make_offer_markdown,
    make_over_cap_text,
    make_pdf_with_outline,
    make_scanned_pdf,
    none_embedder,
    patch_embedder,
    read_document_for_member,
    read_object_bytes,
    run_next_pending_job,
)
from tests.api.helpers import auth_header, register_user


@scenario("../features/attachments.feature", "upload becomes lexical-ready before vectors")
def test_upload_becomes_lexical_ready() -> None:
    pass


@scenario("../features/attachments.feature", "scanned PDF tells the truth")
def test_scanned_pdf_tells_the_truth() -> None:
    pass


@scenario("../features/attachments.feature", "oversized file ingests a capped prefix and says so")
def test_oversized_file_capped_prefix() -> None:
    pass


@scenario("../features/attachments.feature", "a cold embedder never marks an attachment ready")
def test_cold_embedder_never_marks_ready() -> None:
    pass


@scenario("../features/attachments.feature", "spreadsheet upload is steered to product import")
def test_spreadsheet_steered_to_product_import() -> None:
    pass


@scenario("../features/attachments.feature", "document slices answer a query")
def test_document_slices_answer_a_query() -> None:
    pass


@scenario(
    "../features/attachments.feature",
    "section slices work while embeddings are pending",
)
def test_section_slices_work_while_embeddings_pending() -> None:
    pass


@scenario("../features/attachments.feature", "documents never leak across companies")
def test_documents_never_leak_across_companies() -> None:
    pass


@scenario("../features/attachments.feature", "an attached file rides on the next message")
def test_attached_file_rides_on_next_message() -> None:
    pass


@scenario(
    "../features/attachments.feature",
    "zero-instruction upload asks instead of pretending",
)
def test_zero_instruction_upload_asks_instead_of_pretending() -> None:
    pass


@scenario("../features/attachments.feature", "save to library is an HTTP action")
def test_save_to_library_is_http_action() -> None:
    pass


@scenario("../features/attachments.feature", "a chat phrase cannot save to library")
def test_chat_phrase_cannot_save_to_library() -> None:
    pass


@scenario("../features/attachments.feature", "scratch dies with the session")
def test_scratch_dies_with_the_session() -> None:
    pass


def _post_attachment(api, bdd_ctx, filename: str, data: bytes, content_type: str):
    """``POST /api/sessions/{id}/attachments`` — the ADR 0047 §3 upload route."""
    return api.post(
        f"/api/sessions/{bdd_ctx['session_id']}/attachments",
        files={"file": (filename, data, content_type)},
        headers=auth_header(bdd_ctx["access_token"]),
    )


def _drain_attachment_jobs(api, *, limit: int = 8) -> None:
    """Run queued attachment jobs synchronously (ingest → optional embed).

    Bounded: a cold embedder re-enqueues ``attachment_embed``, but the dedupe
    key is one-shot so the queue drains in a couple of passes.
    """
    for _ in range(limit):
        if api.run(run_next_pending_job()) is None:
            return
    raise AssertionError("attachment job queue did not drain")


def _upload_and_ingest(api, bdd_ctx, filename: str, data: bytes, content_type: str) -> uuid.UUID:
    """Upload over real HTTP, run the worker jobs, return the attachment id."""
    res = _post_attachment(api, bdd_ctx, filename, data, content_type)
    assert res.status_code in (200, 201), res.text
    attachment_id = uuid.UUID(res.json()["id"])
    _drain_attachment_jobs(api)
    return attachment_id


def _attachment(api, bdd_ctx):
    return api.run(fetch_attachment_row(bdd_ctx["attachment_id"]))


@given("a member with a session")
def member_with_session(api, bdd_ctx) -> None:
    body = api.run(register_user(api.client, email="bdd-attach@example.com"))
    company_id = body["user"]["organizations"][0]["id"]
    res = api.post(
        "/api/sessions",
        json={"company_id": company_id},
        headers=auth_header(body["access_token"]),
    )
    assert res.status_code == 201, res.text
    bdd_ctx["user_id"] = uuid.UUID(body["user"]["id"])
    bdd_ctx["company_id"] = uuid.UUID(company_id)
    bdd_ctx["session_id"] = uuid.UUID(res.json()["id"])
    bdd_ctx["access_token"] = body["access_token"]


@given("the worker embedder has not finished loading")
def worker_embedder_cold(monkeypatch) -> None:
    patch_embedder(monkeypatch, none_embedder)


@when(parsers.parse('they upload "{filename}" with extractable text'))
def upload_extractable_text(api, bdd_ctx, filename: str) -> None:
    bdd_ctx["attachment_id"] = _upload_and_ingest(
        api, bdd_ctx, filename, make_pdf_with_outline(), "application/pdf"
    )


@when(parsers.parse('they upload "{filename}" with no extractable text'))
def upload_no_text(api, bdd_ctx, filename: str) -> None:
    bdd_ctx["attachment_id"] = _upload_and_ingest(
        api, bdd_ctx, filename, make_scanned_pdf(), "application/pdf"
    )


@when("they upload a file exceeding the chunk cap")
def upload_over_cap(api, bdd_ctx) -> None:
    bdd_ctx["attachment_id"] = _upload_and_ingest(
        api, bdd_ctx, "catalog-huge.txt", make_over_cap_text(), "text/plain"
    )


@when(parsers.parse('they upload "{filename}" as an attachment'))
def upload_attachment_refused(api, bdd_ctx, filename: str) -> None:
    """Upload a file the endpoint is expected to refuse (ADR 0047 §12)."""
    content_type = "text/csv" if filename.endswith(".csv") else "application/octet-stream"
    data = b"sku,name,price\nSKU-1,Milk Tea,48\n"
    bdd_ctx["upload_response"] = _post_attachment(api, bdd_ctx, filename, data, content_type)


@then(parsers.parse('the attachment status becomes "{status}"'))
@then(parsers.parse('the attachment status is "{status}"'))
def attachment_status(api, bdd_ctx, status: str) -> None:
    assert _attachment(api, bdd_ctx).status == status


@then("the digest shows a title, a page count and an outline")
def digest_shows_profile(api, bdd_ctx) -> None:
    profile = _attachment(api, bdd_ctx).doc_profile
    assert profile["title"]
    assert isinstance(profile["pages"], int) and profile["pages"] >= 1
    assert isinstance(profile["outline"], list) and profile["outline"]


@then("the error says the file has no readable text")
def error_says_no_readable_text(api, bdd_ctx) -> None:
    error = _attachment(api, bdd_ctx).error or ""
    assert error
    assert "text" in error.lower() or "讀唔到字" in error


@then(parsers.parse('no chunk is stored without a vector under status "{status}"'))
def no_vectorless_chunk_under_status(api, bdd_ctx, status: str) -> None:
    row = _attachment(api, bdd_ctx)
    if row.status == status:
        chunks = api.run(fetch_chunk_rows(bdd_ctx["attachment_id"]))
        assert chunks
        assert all(chunk.embedding is not None for chunk in chunks)


@then("only the first capped chunks are ingested")
def capped_prefix_ingested(api, bdd_ctx) -> None:
    chunks = api.run(fetch_chunk_rows(bdd_ctx["attachment_id"]))
    assert len(chunks) == ChunkConfig().max_chunks == 150
    assert [chunk.chunk_index for chunk in chunks] == list(range(ChunkConfig().max_chunks))


@then("the digest marks the document partial")
def digest_marks_partial(api, bdd_ctx) -> None:
    assert _attachment(api, bdd_ctx).doc_profile["partial"] is True


@then("the upload is refused with a pointer to product import")
def refused_with_product_import_pointer(api, bdd_ctx) -> None:
    """ADR 0047 §12: 400 whose detail names the product import route."""
    res = bdd_ctx["upload_response"]
    assert res.status_code == 400, res.text
    assert "products/import" in res.text


# --- document retrieve (read_document seam) ------------------------------------


def _read_document(api, bdd_ctx, *, query=None, section=None, attachment_id=None):
    """Drive the invented ``read_document`` seam as the member in context."""
    return api.run(
        read_document_for_member(
            company_id=bdd_ctx["company_id"],
            user_id=bdd_ctx["user_id"],
            attachment_id=attachment_id or bdd_ctx["attachment_id"],
            query=query,
            section=section,
        )
    )


@given("the member has a ready attachment with an offer section")
def member_has_offer_attachment(api, bdd_ctx, monkeypatch) -> None:
    """ "ready" here means retrievable: ``ready_lexical`` counts (ADR 0047 §7 —
    lexical + section slices already serve before vectors land). The offer
    doc is .md because the pdfium fixtures are ASCII-only."""
    patch_embedder(monkeypatch, none_embedder)
    bdd_ctx["attachment_id"] = _upload_and_ingest(
        api, bdd_ctx, "offers.md", make_offer_markdown(), "text/markdown"
    )
    assert _attachment(api, bdd_ctx).status in {"ready_lexical", "ready"}


@given("an attachment whose embeddings are still running")
def attachment_embeddings_still_running(api, bdd_ctx, monkeypatch) -> None:
    patch_embedder(monkeypatch, none_embedder)
    bdd_ctx["attachment_id"] = _upload_and_ingest(
        api, bdd_ctx, "offers.md", make_offer_markdown(), "text/markdown"
    )
    assert _attachment(api, bdd_ctx).status == "ready_lexical"


@given("a member of another company has an attachment")
def other_company_member_has_attachment(api, bdd_ctx, monkeypatch) -> None:
    patch_embedder(monkeypatch, none_embedder)
    body = api.run(register_user(api.client, email="bdd-other-co@example.com"))
    company_id = body["user"]["organizations"][0]["id"]
    res = api.post(
        "/api/sessions",
        json={"company_id": company_id},
        headers=auth_header(body["access_token"]),
    )
    assert res.status_code == 201, res.text
    up = api.post(
        f"/api/sessions/{res.json()['id']}/attachments",
        files={"file": ("offers.md", make_offer_markdown(), "text/markdown")},
        headers=auth_header(body["access_token"]),
    )
    assert up.status_code in (200, 201), up.text
    bdd_ctx["other_attachment_id"] = uuid.UUID(up.json()["id"])
    _drain_attachment_jobs(api)


@when(parsers.parse('document slices are requested for "{term}"'))
def request_slices_for_query(api, bdd_ctx, term: str) -> None:
    bdd_ctx["read_result"] = _read_document(api, bdd_ctx, query=term)


@when(parsers.parse('document slices are requested for the section "{section}"'))
def request_slices_for_section(api, bdd_ctx, section: str) -> None:
    bdd_ctx["section"] = section
    bdd_ctx["read_result"] = _read_document(api, bdd_ctx, section=section)


@when("the first member requests that attachment")
def first_member_requests_attachment(api, bdd_ctx) -> None:
    """Chosen probe: the ``read_document`` seam with the first member's
    company_id/user_id against the other company's attachment id. (The HTTP
    download route's cross-company refusal is already pinned by
    test_session_attachments.py — the service seam is what §14 re-checks.)"""
    bdd_ctx["read_result"] = _read_document(
        api, bdd_ctx, attachment_id=bdd_ctx["other_attachment_id"]
    )


@then("at most 5 slices are returned")
def at_most_five_slices(api, bdd_ctx) -> None:
    result = bdd_ctx["read_result"]
    assert result is not None
    assert 1 <= len(result["slices"]) <= 5


@then("every slice carries a chunk id, a page or section ref and text")
def every_slice_carries_id_ref_text(api, bdd_ctx) -> None:
    for s in bdd_ctx["read_result"]["slices"]:
        uuid.UUID(s["chunk_id"])  # grounding id parses as a uuid
        assert isinstance(s["ref"], str) and s["ref"].strip()
        assert isinstance(s["text"], str) and s["text"].strip()


@then("the slices come from that heading path")
def slices_come_from_heading_path(api, bdd_ctx) -> None:
    result = bdd_ctx["read_result"]
    assert result is not None and result["slices"]
    chunks = api.run(fetch_chunk_rows(bdd_ctx["attachment_id"]))
    paths = {str(c.id): (c.heading_path or "") for c in chunks}
    for s in result["slices"]:
        assert bdd_ctx["section"] in paths.get(s["chunk_id"], "")


@then("the result is marked partial")
def result_marked_partial(api, bdd_ctx) -> None:
    assert bdd_ctx["read_result"]["partial"] is True


@then("the request is refused")
def request_is_refused(api, bdd_ctx) -> None:
    """Refusal shape: the seam returns ``None`` for out-of-scope ids."""
    assert bdd_ctx["read_result"] is None


# --- session wiring (attachment_ids / save / GC — ADR 0047 §2/§3/§5/§13) --------
#
# Invented names (mirrored in attachment_helpers.py and
# test_session_attachment_wiring.py): PostMessageRequest.attachment_ids;
# user-message metadata["attachment_ids"]; MessageResponse.attachments digest
# chips {id, filename, status}; session.state["attachments"] hydrated digests;
# POST /api/attachments/{id}/save flips the caller's scratch to owner_scope
# "user"; session delete reclaims scratch rows + chunks + bytes when the last
# attachment_sessions reference dies.


@given("the member has a ready attachment in the session")
def member_has_ready_session_attachment(api, bdd_ctx, monkeypatch) -> None:
    """Upload + drain jobs (``ready_lexical`` counts as ready, §7) and stub the
    session graph so the follow-up POST /messages runs without LLM keys."""
    patch_embedder(monkeypatch, none_embedder)
    bdd_ctx["attachment_id"] = _upload_and_ingest(
        api, bdd_ctx, "offers.md", make_offer_markdown(), "text/markdown"
    )
    assert _attachment(api, bdd_ctx).status in {"ready_lexical", "ready"}
    set_session_graph(StubSessionGraph())


@given("the member has a session-scoped attachment")
def member_has_session_scoped_attachment(api, bdd_ctx, monkeypatch) -> None:
    """Upload + drain so attachment row, chunks and bytes all exist."""
    patch_embedder(monkeypatch, none_embedder)
    bdd_ctx["attachment_id"] = _upload_and_ingest(
        api, bdd_ctx, "offers.md", make_offer_markdown(), "text/markdown"
    )
    row = _attachment(api, bdd_ctx)
    assert row.owner_scope == "session"
    assert row.session_id == bdd_ctx["session_id"]
    bdd_ctx["object_key"] = row.object_key
    assert api.run(fetch_chunk_count(bdd_ctx["attachment_id"])) > 0
    assert api.run(read_object_bytes(row.object_key)) is not None


def _post_session_message(api, bdd_ctx, content: str) -> None:
    """POST /messages carrying ``attachment_ids`` for the attachment in context."""
    res = api.post(
        f"/api/sessions/{bdd_ctx['session_id']}/messages",
        json={
            "content": content,
            "attachment_ids": [str(bdd_ctx["attachment_id"])],
        },
        headers=auth_header(bdd_ctx["access_token"]),
    )
    assert res.status_code == 200, res.text
    bdd_ctx["message_response"] = res.json()


def _last_user_message(bdd_ctx) -> dict:
    users = [m for m in bdd_ctx["message_response"]["messages"] if m["role"] == "user"]
    assert users, "no user message in POST /messages response"
    return users[-1]


def _attachment_digest(entries, attachment_id) -> dict | None:
    return next(
        (d for d in entries or [] if str(d.get("id")) == str(attachment_id)),
        None,
    )


@when("they send a message with the attachment")
def send_message_with_attachment(api, bdd_ctx) -> None:
    _post_session_message(api, bdd_ctx, "用呢份嘢出個 post")


@then("the message references the attachment")
def message_references_attachment(api, bdd_ctx) -> None:
    """The persisted user message stores ``metadata.attachment_ids`` and the
    response carries the ``attachments`` digest chip ``{id, filename, status}``."""
    msg = _last_user_message(bdd_ctx)
    attachment_id = bdd_ctx["attachment_id"]
    stored_ids = [str(i) for i in (msg.get("metadata") or {}).get(MESSAGE_ATTACHMENT_IDS_KEY) or []]
    assert str(attachment_id) in stored_ids, (
        f"user message metadata lacks {MESSAGE_ATTACHMENT_IDS_KEY}: {msg}"
    )
    digest = _attachment_digest(msg.get(MESSAGE_ATTACHMENTS_FIELD), attachment_id)
    assert digest is not None, f"message carries no attachment digest: {msg}"
    assert digest.get("filename")
    assert digest.get("status")


@then("the session carries the attachment digest")
def session_carries_attachment_digest(api, bdd_ctx) -> None:
    """``session.state["attachments"]`` holds the hydrated digest (§5/§13):
    ``{id, filename, status, doc_profile subset}``."""
    session = api.run(fetch_session_row(bdd_ctx["session_id"]))
    assert session is not None
    digests = (session.state or {}).get(STATE_ATTACHMENTS_KEY) or []
    digest = _attachment_digest(digests, bdd_ctx["attachment_id"])
    assert digest is not None, (
        f"session.state[{STATE_ATTACHMENTS_KEY!r}] lacks the digest: {digests}"
    )
    assert digest.get("filename")
    assert digest.get("status")
    assert any(k in digest for k in DIGEST_PROFILE_KEYS), (
        f"digest misses the doc_profile subset: {digest}"
    )


@when("they post the attachment to their library")
def post_attachment_to_library(api, bdd_ctx) -> None:
    """§2 save-to-library is an explicit HTTP action, never a chat phrase."""
    res = api.post(
        SAVE_ATTACHMENT_PATH.format(attachment_id=bdd_ctx["attachment_id"]),
        headers=auth_header(bdd_ctx["access_token"]),
    )
    assert res.status_code == 200, res.text
    assert res.json()["owner_scope"] == "user"
    bdd_ctx["save_response"] = res.json()


@then("a committed user-scope document exists")
def committed_user_scope_document_exists(api, bdd_ctx) -> None:
    row = _attachment(api, bdd_ctx)
    assert row.owner_scope == "user"
    assert row.user_id == bdd_ctx["user_id"]


@then("the document survives the session")
def document_survives_the_session(api, bdd_ctx) -> None:
    """Delete the originating session — a saved row is library, not scratch."""
    res = api.request(
        "DELETE",
        f"/api/sessions/{bdd_ctx['session_id']}",
        headers=auth_header(bdd_ctx["access_token"]),
    )
    assert res.status_code == 204, res.text
    row = _attachment(api, bdd_ctx)
    assert row.owner_scope == "user"
    assert api.run(read_object_bytes(row.object_key)) is not None


@when("they send a message asking to save it")
def send_message_asking_to_save(api, bdd_ctx) -> None:
    """「幫我存入我嘅庫」— a chat phrase, not a commit (§2 / ADR 0011)."""
    _post_session_message(api, bdd_ctx, "幫我存入我嘅庫")


@then("no committed document exists for the member")
def no_committed_document_for_member(api, bdd_ctx) -> None:
    """Chat never commits: the scratch row stays session-scoped and no
    user-scope attachment appears for the member."""
    row = _attachment(api, bdd_ctx)
    assert row.owner_scope == "session"
    saved = api.run(list_attachment_rows(user_id=bdd_ctx["user_id"], owner_scope="user"))
    assert saved == []


@when("the session is deleted")
def session_is_deleted(api, bdd_ctx) -> None:
    res = api.request(
        "DELETE",
        f"/api/sessions/{bdd_ctx['session_id']}",
        headers=auth_header(bdd_ctx["access_token"]),
    )
    assert res.status_code == 204, res.text


@then("the attachment rows and the stored object are removed")
def attachment_rows_and_object_removed(api, bdd_ctx) -> None:
    """Last referencing session died → attachment row, document_chunks,
    attachment_sessions rows and object bytes are all reclaimed (§13)."""
    attachment_id = bdd_ctx["attachment_id"]
    assert api.run(fetch_attachment_or_none(attachment_id)) is None
    assert api.run(fetch_chunk_count(attachment_id)) == 0
    assert api.run(fetch_join_rows(attachment_id)) == []
    assert api.run(read_object_bytes(bdd_ctx["object_key"])) is None


# --- read_attachment chat tool (ADR 0047 §5/§6/§8/§14) ----------------------------
#
# The zero-instruction scenario runs the REAL compiled session graph — the
# Given's StubSessionGraph is swapped out in the When step — with a canned
# ``route_intent`` classifier (``complete_json`` → intent="chat") and a
# FunctionModel that only produces the offering reply when the prompt it
# was served carries the attachment digest. Everything between POST
# /messages and the chat node — _invoke_graph, digest hydration,
# _chat_stream, the Pydantic AI harness — runs for real.


def _last_assistant_message(bdd_ctx) -> dict:
    assistants = [m for m in bdd_ctx["message_response"]["messages"] if m["role"] == "assistant"]
    assert assistants, "no assistant message in POST /messages response"
    return assistants[-1]


@when("they send a message with only the attachment")
def send_message_with_only_attachment(api, bdd_ctx, monkeypatch) -> None:
    """POST /messages with ``attachment_ids`` and a minimal content through
    the real graph; the FunctionModel crafts the §8 offering reply only
    when the prompt carries the digest — red until ``_chat_stream`` wires
    ``state["attachments"]`` into the payload."""
    import json as _json

    from internal.session import harness as H
    from internal.session import nodes as N

    set_session_graph(None)  # real graph — the Given set a StubSessionGraph
    monkeypatch.setattr(N, "has_llm_credentials", lambda: True)

    async def _route_json(**_kwargs):
        # Canned intent classifier — keeps the turn deterministic while
        # everything else (chat node, harness, hydration) runs for real.
        return _json.dumps({"intent": "chat", "research": {}})

    monkeypatch.setattr(N, "complete_json", _route_json)

    row = _attachment(api, bdd_ctx)
    title = str((row.doc_profile or {}).get("title") or row.filename)
    bdd_ctx["digest_filename"] = row.filename
    bdd_ctx["digest_title"] = title
    reply = (
        f"收到 {row.filename}（{title}）。我可以幫你："
        "用呢份嘢出 post、存入我嘅庫、或者講吓重點。想點？"
    )
    seen: dict = {}
    monkeypatch.setattr(
        H,
        "_model_override",
        make_digest_probe_model(
            filename=row.filename,
            title=title,
            reply=reply,
            seen=seen,
        ),
    )
    bdd_ctx["model_seen"] = seen
    _post_session_message(api, bdd_ctx, "用呢份嘢")


@then("the assistant reply carries the document digest")
def assistant_reply_carries_document_digest(bdd_ctx) -> None:
    """§8/§5: the reply quotes digest facts (filename + title) — which the
    FunctionModel only writes when the prompt actually carried the digest."""
    seen = bdd_ctx.get("model_seen") or {}
    assert seen.get("saw_full_text") is not True, (
        "chat prompt leaked a non-digest field — §5 digest-only violation"
    )
    assert seen.get("saw_attachments_key"), (
        f"no attachments digest in the chat prompt; model saw: {seen}"
    )
    content = _last_assistant_message(bdd_ctx)["content"]
    assert content != "MISSING-DIGEST-SENTINEL", f"chat prompt carried no digest; model saw: {seen}"
    assert bdd_ctx["digest_filename"] in content
    assert bdd_ctx["digest_title"] in content


@then("the reply offers actions for drafting, saving and summarizing")
def reply_offers_draft_save_summarize_actions(bdd_ctx) -> None:
    """§8: ambiguity asks — the reply offers draft / save-to-library /
    summarize actions instead of pretending the doc was read."""
    content = _last_assistant_message(bdd_ctx)["content"]
    assert "post" in content.lower() or "出帖" in content, (
        f"no drafting action offered: {content!r}"
    )
    assert "存入" in content, f"no save-to-library action offered: {content!r}"
    assert "重點" in content or "講吓" in content, f"no summarize action offered: {content!r}"
