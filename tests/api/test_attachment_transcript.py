"""API-tier tests for the ADR 0048 OCR transcript contract.

Invented contract the transcript step must satisfy:

- ``POST /api/attachments/{attachment_id}/transcript`` — JSON body
  ``{"engine": str | None, "pages": [{"page": int, "text": str}]}``, auth +
  scope identical to ``GET …/download`` (unknown / cross-company /
  non-owner for ``session``|``user`` rows → uniform 404). Lives in
  ``cmd/api/routes/attachments.py`` next to download/save.
- Only ``needs_ocr`` rows accept a transcript (any other status → 409).
- Pages are validated against ``doc_profile["pages"]`` (out-of-range → 400);
  an all-empty transcript → 400.
- On success the transcript is stored as object bytes at
  ``attachments/{id}/transcript.json`` (ADR 0048 §4 — re-chunk / re-embed
  must never re-OCR), a fresh ``attachment_ingest`` job is enqueued under
  dedupe key ``attachment_ingest:{id}:transcript``, and the row stays
  ``needs_ocr`` until the job runs.
- The worker resolves ``needs_ocr`` + stored transcript via
  ``document_parse.parse_transcript`` — then the unchanged
  chunk → ``ready_lexical`` → embed → ``ready`` pipeline. ``doc_profile``
  gains ``"ocr": true`` + ``"engine"`` provenance (§5).

None of this exists yet — imports stay inside helpers/test bodies so
collection succeeds and each test fails on the missing route/seam,
never at collection.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api.attachment_helpers import (
    ATTACHMENT_INGEST_KIND,
    fetch_attachment,
    fetch_chunks,
    fetch_jobs,
    make_pdf_with_outline,
    make_scanned_pdf,
    patch_embedder,
    read_object_bytes,
    run_next_job,
    seed_session,
    warm_embedder,
)
from tests.api.helpers import auth_header, register_user

TRANSCRIPT_PATH = "/api/attachments/{attachment_id}/transcript"
"""ADR 0048 §2 route — POST body ``{engine, pages: [{page, text}]}``."""

TRANSCRIPT_KEY = "attachments/{attachment_id}/transcript.json"
"""§4 object key — canonical parsed text for OCR'd docs."""

TRANSCRIPT_INGEST_DEDUPE = "attachment_ingest:{attachment_id}:transcript"
"""§3 — transcript ingest re-uses the ``attachment_ingest`` job kind with a
dedupe suffix; the first-parse key is already consumed."""

GOOD_TRANSCRIPT = {
    "engine": "tesseract.js",
    "pages": [{"page": 1, "text": "招牌奶茶 $48\n\n凍檸茶 $36"}],
}


async def _upload_attachment(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    filename: str,
    data: bytes,
    content_type: str = "application/pdf",
) -> tuple[str, uuid.UUID]:
    """Register a member + session, POST the file, run one ingest job."""
    body = await register_user(client)
    token = body["access_token"]
    user_id = uuid.UUID(body["user"]["id"])
    company_id = uuid.UUID(body["user"]["organizations"][0]["id"])
    session = await seed_session(db_session, user_id=user_id, company_id=company_id)
    await db_session.commit()  # the API request reads through another session
    res = await client.post(
        f"/api/sessions/{session.id}/attachments",
        files={"file": (filename, data, content_type)},
        headers=auth_header(token),
    )
    assert res.status_code == 201, res.text
    attachment_id = uuid.UUID(res.json()["id"])
    job = await run_next_job(db_session)
    assert job is not None and job.status == "succeeded"
    return token, attachment_id


async def _upload_needs_ocr(
    client: AsyncClient, db_session: AsyncSession
) -> tuple[str, uuid.UUID]:
    token, attachment_id = await _upload_attachment(
        client, db_session, filename="menu-scan.pdf", data=make_scanned_pdf()
    )
    row = await fetch_attachment(db_session, attachment_id)
    assert row.status == "needs_ocr"
    return token, attachment_id


def _post_transcript(client: AsyncClient, token: str, attachment_id, payload):
    return client.post(
        TRANSCRIPT_PATH.format(attachment_id=attachment_id),
        json=payload,
        headers=auth_header(token),
    )


@pytest.mark.asyncio
async def test_transcript_recovers_scanned_pdf_through_same_pipeline(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0048 §3: transcript → stored bytes → fresh ingest job → the
    unchanged chunk/embed pipeline lands page-referenced chunks."""
    patch_embedder(monkeypatch, warm_embedder)
    token, attachment_id = await _upload_needs_ocr(client, db_session)

    res = await _post_transcript(client, token, attachment_id, GOOD_TRANSCRIPT)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "needs_ocr"  # parked until the job runs

    stored = await read_object_bytes(TRANSCRIPT_KEY.format(attachment_id=attachment_id))
    assert stored is not None and "招牌奶茶" in stored.decode()

    jobs = await fetch_jobs(db_session, kind=ATTACHMENT_INGEST_KIND)
    assert any(
        j.dedupe_key
        == TRANSCRIPT_INGEST_DEDUPE.format(attachment_id=attachment_id)
        for j in jobs
    )

    # End the open transaction so claim_next_job's func.now() (= CURRENT_
    # TIMESTAMP, frozen at txn start) postdates the job's run_after —
    # otherwise the freshly-enqueued job looks "not yet due" here while a
    # real worker (fresh txn per claim) would pick it up fine.
    await db_session.commit()
    job = await run_next_job(db_session)
    assert job is not None and job.status == "succeeded"

    row = await fetch_attachment(db_session, attachment_id)
    assert row.status == "ready"
    assert row.doc_profile["ocr"] is True
    assert row.doc_profile["engine"] == "tesseract.js"
    chunks = await fetch_chunks(db_session, attachment_id)
    assert chunks
    assert all(c.page_start == 1 and c.page_end == 1 for c in chunks)
    assert any("招牌奶茶" in c.text for c in chunks)


@pytest.mark.asyncio
async def test_transcript_on_healthy_attachment_conflicts(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2: only ``needs_ocr`` rows accept a transcript — a doc that already
    ingested normally must not be silently re-chunked by client text."""
    patch_embedder(monkeypatch, warm_embedder)
    token, attachment_id = await _upload_attachment(
        client, db_session, filename="catalog2026.pdf", data=make_pdf_with_outline()
    )
    row = await fetch_attachment(db_session, attachment_id)
    assert row.status == "ready"

    res = await _post_transcript(client, token, attachment_id, GOOD_TRANSCRIPT)
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_transcript_unknown_attachment_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body = await register_user(client)
    res = await _post_transcript(
        client, body["access_token"], uuid.uuid4(), GOOD_TRANSCRIPT
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_transcript_cross_company_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Existence never leaks (ADR 0047 §14): another company's parked
    attachment refuses a transcript the same way it refuses download."""
    _token, attachment_id = await _upload_needs_ocr(client, db_session)
    other = await register_user(client)

    res = await _post_transcript(client, other["access_token"], attachment_id, GOOD_TRANSCRIPT)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_transcript_page_out_of_bounds_is_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Pages are validated against the parked profile's page count — the
    client cannot invent a page 9 for a 1-page scan."""
    token, attachment_id = await _upload_needs_ocr(client, db_session)

    res = await _post_transcript(
        client, token, attachment_id, {"pages": [{"page": 9, "text": "唔存在嘅頁"}]}
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_transcript_all_blank_is_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """An all-empty transcript contributes nothing — refuse up front rather
    than enqueue a doomed ingest."""
    token, attachment_id = await _upload_needs_ocr(client, db_session)

    res = await _post_transcript(
        client, token, attachment_id, {"pages": [{"page": 1, "text": "   \n\n  "}]}
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_transcript_reingest_without_new_submission(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§4: the stored transcript is canonical — a re-ingest (embed-model
    change, chunker fix) re-chunks from ``transcript.json`` and never
    needs the client again."""
    patch_embedder(monkeypatch, warm_embedder)
    token, attachment_id = await _upload_needs_ocr(client, db_session)
    res = await _post_transcript(client, token, attachment_id, GOOD_TRANSCRIPT)
    assert res.status_code == 200
    await db_session.commit()  # fresh txn — see the func.now() note above
    assert await run_next_job(db_session) is not None

    # Simulate a re-chunk trigger: drop the chunks and re-park the row —
    # the re-run must rebuild from transcript.json, not the original
    # bytes (re-parsing the scan would land right back at needs_ocr).
    from sqlalchemy import delete

    from internal.memory import repos
    from internal.memory.models import DocumentChunk

    await db_session.execute(
        delete(DocumentChunk).where(DocumentChunk.attachment_id == attachment_id)
    )
    row = await fetch_attachment(db_session, attachment_id)
    row.status = "needs_ocr"
    await repos.enqueue_job(
        db_session,
        kind=ATTACHMENT_INGEST_KIND,
        payload={"attachment_id": str(attachment_id)},
        dedupe_key=f"{ATTACHMENT_INGEST_KIND}:{attachment_id}:round2",
    )
    await db_session.commit()
    job = await run_next_job(db_session)
    assert job is not None and job.status == "succeeded"

    row = await fetch_attachment(db_session, attachment_id)
    assert row.status == "ready"
    chunks = await fetch_chunks(db_session, attachment_id)
    assert any("凍檸茶" in c.text for c in chunks)
