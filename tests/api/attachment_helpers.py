"""Shared helpers for ADR 0047 attachment ingest tests.

These helpers pin the ingest seam the future ``POST /sessions/{id}/attachments``
will use: bytes land in the media object store under ``attachments/``, a pending
``Attachment`` row points at the object key, and a job on the ADR 0039 queue
drives parse -> profile -> chunk -> embed in the worker.

Invented contract the ingest step must satisfy:
- ``internal.memory.document_ingest.run_attachment_ingest(db, *, attachment_id)``
- ``internal.memory.document_ingest.run_attachment_embed(db, *, attachment_id)``
- job kinds ``attachment_ingest`` / ``attachment_embed`` registered in
  ``cmd.worker.main._JOB_HANDLERS``; payload ``{"attachment_id": "<uuid>"}``;
  dedupe keys ``f"{kind}:{attachment_id}"``.
- ``internal.memory.embeddings.embedding_model_name()`` — public accessor for
  the active model id (wraps ``_model_name()``).
- ``doc_profile``: ``title``, ``pages``, ``outline``, ``kind_guess``
  (``"catalog"`` for SKU/price-dense docs | ``"document"`` fallback),
  ``preview``, ``partial``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory import repos
from internal.memory.database import open_session
from internal.memory.embeddings import EMBEDDING_DIM
from internal.memory.models import Attachment, AttachmentSession, DocumentChunk, Job, Session

ATTACHMENT_INGEST_KIND = "attachment_ingest"
ATTACHMENT_EMBED_KIND = "attachment_embed"


def attachment_ingest_dedupe_key(attachment_id: uuid.UUID) -> str:
    return f"{ATTACHMENT_INGEST_KIND}:{attachment_id}"


def attachment_embed_dedupe_key(attachment_id: uuid.UUID) -> str:
    return f"{ATTACHMENT_EMBED_KIND}:{attachment_id}"


# --- document fixtures ------------------------------------------------------


def _pdf_stream(text: str) -> bytes:
    body = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode()
    return b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream"


def _pdf_doc(objs: list[bytes]) -> bytes:
    out = b"%PDF-1.4\n"
    for i, obj in enumerate(objs, 1):
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    trailer = b"trailer\n<< /Root 1 0 R /Size " + str(len(objs) + 1).encode() + b" >>\n%%EOF"
    return out + trailer


def make_pdf(pages: list[str | None]) -> bytes:
    """Minimal PDF (no xref — pdfium reconstructs). None = page without /Contents."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font_id = 3 + 2 * len(pages)
    for i, text in enumerate(pages):
        contents = f"/Contents {4 + 2 * i} 0 R" if text is not None else ""
        objs.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> {contents} >>"
            ).encode()
        )
        objs.append(_pdf_stream(text) if text is not None else b"<< >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    return _pdf_doc(objs)


def make_pdf_with_outline() -> bytes:
    """Two-page PDF whose TOC lands as ``Intro`` / ``Details`` heading blocks."""
    return _pdf_doc(
        [
            b"<< /Type /Catalog /Pages 2 0 R /Outlines 3 0 R >>",
            b"<< /Type /Pages /Kids [4 0 R 6 0 R] /Count 2 >>",
            b"<< /Type /Outlines /First 8 0 R /Last 9 0 R /Count 2 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 10 0 R >> >> /Contents 5 0 R >>",
            _pdf_stream("Page one body"),
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 10 0 R >> >> /Contents 7 0 R >>",
            _pdf_stream("Page two body"),
            b"<< /Title (Intro) /Parent 3 0 R /Next 9 0 R /Dest [4 0 R /Fit] >>",
            b"<< /Title (Details) /Parent 3 0 R /Prev 8 0 R /Dest [6 0 R /Fit] >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
    )


def make_scanned_pdf() -> bytes:
    """One page with no /Contents — no extractable text."""
    return make_pdf([None])


def make_over_cap_text(paragraphs: int = 300) -> bytes:
    """Enough paragraphs to exceed the chunk cap under any token counter."""
    parts = []
    for i in range(paragraphs):
        sentences = " ".join(
            f"Menu item {i}-{j} tastes great and sells well every day." for j in range(4)
        )
        parts.append(f"Section {i} overview. {sentences}")
    return "\n\n".join(parts).encode()


def make_catalog_text() -> bytes:
    """SKU + price dense doc — should read as a catalog/price-list kind."""
    lines = []
    for i in range(40):
        lines.append(f"SKU-{1000 + i} 招牌奶茶 $48")
        lines.append(f"SKU-{2000 + i} 凍檸茶 $36")
    return "\n".join(lines).encode()


def make_prose_text() -> bytes:
    """Plain narrative doc — no SKU/price/table signal."""
    paragraphs = [
        f"本店自二零一零年起用心沖調每一杯奶茶。第 {i} 段：我們堅持每日新鮮製作，"
        "選用優質茶葉與淡奶，為顧客帶來最地道的香港味道。"
        for i in range(8)
    ]
    return "\n\n".join(paragraphs).encode()


# --- DB seeding -------------------------------------------------------------


async def seed_session(db: AsyncSession, *, user_id: uuid.UUID, company_id: uuid.UUID) -> Session:
    session = Session(user_id=user_id, company_id=company_id, mode="CHAT", state={})
    db.add(session)
    await db.flush()
    return session


async def seed_pending_attachment(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    session_id: uuid.UUID,
    filename: str,
    data: bytes,
    content_type: str,
) -> uuid.UUID:
    """Seed the upload seam: object bytes + pending row + session join + ingest job."""
    from internal.media.storage import put_bytes

    attachment_id = uuid.uuid4()
    object_key = f"attachments/{attachment_id}/{filename}"
    await put_bytes(key=object_key, data=data, content_type=content_type)
    db.add(
        Attachment(
            id=attachment_id,
            company_id=company_id,
            owner_scope="session",
            user_id=user_id,
            session_id=session_id,
            filename=filename,
            content_type=content_type,
            object_key=object_key,
            status="pending",
            doc_profile={},
        )
    )
    db.add(AttachmentSession(attachment_id=attachment_id, session_id=session_id))
    await repos.enqueue_job(
        db,
        kind=ATTACHMENT_INGEST_KIND,
        payload={"attachment_id": str(attachment_id)},
        dedupe_key=attachment_ingest_dedupe_key(attachment_id),
    )
    await db.commit()
    return attachment_id


# --- job queue driver -------------------------------------------------------


async def run_next_job(db: AsyncSession, *, worker_id: str = "attachment-test-worker") -> Job | None:
    """Claim one pending job and dispatch it the way ``cmd.worker._run_one_job`` does."""
    from cmd.worker.main import _JOB_HANDLERS

    job = await repos.claim_next_job(db, worker_id=worker_id)
    await db.commit()
    if job is None:
        return None
    handler = _JOB_HANDLERS[job.kind]
    try:
        await handler(db, job)
    except Exception as exc:
        await db.rollback()
        await repos.finish_job(db, job, ok=False, error=str(exc))
    else:
        await repos.finish_job(db, job, ok=True)
    await db.commit()
    return job


async def run_next_pending_job(*, worker_id: str = "attachment-test-worker") -> Job | None:
    """Open-session variant of ``run_next_job`` for sync BDD steps."""
    async with open_session() as db:
        return await run_next_job(db, worker_id=worker_id)


async def run_ingest(db: AsyncSession, attachment_id: uuid.UUID) -> None:
    """Run the ingest handler directly (the function the worker dispatches)."""
    from internal.memory.document_ingest import run_attachment_ingest

    await run_attachment_ingest(db, attachment_id=attachment_id)
    await db.commit()


async def run_embed(db: AsyncSession, attachment_id: uuid.UUID) -> None:
    """Run the second-phase embed handler directly."""
    from internal.memory.document_ingest import run_attachment_embed

    await run_attachment_embed(db, attachment_id=attachment_id)
    await db.commit()


# --- reads ------------------------------------------------------------------


async def fetch_attachment(db: AsyncSession, attachment_id: uuid.UUID) -> Attachment:
    row = await db.get(Attachment, attachment_id)
    assert row is not None
    return row


async def fetch_chunks(db: AsyncSession, attachment_id: uuid.UUID) -> list[DocumentChunk]:
    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.attachment_id == attachment_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return list(result.scalars().all())


async def fetch_jobs(db: AsyncSession, *, kind: str | None = None) -> list[Job]:
    stmt = select(Job).order_by(Job.created_at)
    if kind is not None:
        stmt = stmt.where(Job.kind == kind)
    return list((await db.execute(stmt)).scalars().all())


async def fetch_attachment_row(attachment_id: uuid.UUID) -> Attachment:
    """Open-session variant for sync BDD steps."""
    async with open_session() as db:
        return await fetch_attachment(db, attachment_id)


async def fetch_chunk_rows(attachment_id: uuid.UUID) -> list[DocumentChunk]:
    async with open_session() as db:
        return await fetch_chunks(db, attachment_id)


# --- embedder seams ----------------------------------------------------------


def none_embedder(texts: list[str]) -> list[list[float] | None]:
    """Cold embedder: the model has not finished loading (ADR 0047 §7)."""
    return [None] * len(texts)


def warm_embedder(texts: list[str]) -> list[list[float] | None]:
    return [[0.001 * (i + 1) for i in range(EMBEDDING_DIM)] for _ in texts]


def patch_embedder(
    monkeypatch: pytest.MonkeyPatch,
    fn: Callable[[list[str]], list[list[float] | None]],
) -> None:
    """Patch ``embed_texts`` everywhere the ingest path may look it up.

    ``internal.memory.embeddings.embed_texts`` covers module-attribute call
    sites; ``document_ingest.embed_texts`` covers a ``from ... import`` binding
    (same pattern as ``repos.embed_texts``).
    """
    from internal.memory import embeddings

    monkeypatch.setattr(embeddings, "embed_texts", fn)
    try:
        from internal.memory import document_ingest
    except ImportError:
        return
    monkeypatch.setattr(document_ingest, "embed_texts", fn, raising=False)


def active_embedding_model_name() -> str:
    """The model id the impl must stamp on ``DocumentChunk.embedding_model``."""
    from internal.memory.embeddings import embedding_model_name

    return embedding_model_name()
