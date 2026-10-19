"""Worker-side attachment ingest (ADR 0047 §5/§7/§10).

Pipeline: object-store bytes → ``parse_document`` → deterministic
``doc_profile`` → ``chunk_blocks`` → ``document_chunks`` rows → status
``ready_lexical`` → batched ``embed_texts`` → ``ready`` only when every
chunk carries a vector for the active ``embedding_model``. Chunks left
``NULL`` keep ``ready_lexical`` and enqueue an ``attachment_embed`` job
(dedupe key ``attachment_embed:{id}``).

Parse/storage failures are **permanent**: the row goes ``failed`` +
``error`` and the handler returns — the job itself succeeds, a corrupt
file never burns job retries (§10). Unexpected exceptions propagate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from botocore.exceptions import ClientError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.media.storage import (
    MediaStorageError,
    attachment_transcript_key,
    get_bytes,
)
from internal.memory import embeddings, repos
from internal.memory.document_chunk import (
    ChunkConfig,
    chunk_blocks,
    embed_text_for,
)
from internal.memory.document_parse import (
    DocumentBlock,
    NoExtractableTextError,
    ParsedDocument,
    TranscriptPage,
    parse_document,
    parse_transcript,
)
from internal.memory.embeddings import embedding_model_name
from internal.memory.models import Attachment, DocumentChunk

logger = logging.getLogger(__name__)

ATTACHMENT_INGEST_KIND = "attachment_ingest"
ATTACHMENT_EMBED_KIND = "attachment_embed"

_EMBED_BATCH = 32
# Cold-embedder follow-ups are bounded — after this many reschedules the row
# stays honestly ``ready_lexical`` (lexical retrieval still works).
_EMBED_MAX_RESCHEDULES = 8
_EMBED_RESCHEDULE_BASE_SECONDS = 30
_EMBED_RESCHEDULE_MAX_SECONDS = 300

# kind_guess: a line counts as catalog-ish when it carries a SKU-style code
# (SKU-1234 / #1234) or an explicit price token ($48 / HK$48 / ¥48 / 48元).
_CATALOG_LINE_RE = re.compile(
    r"(?:SKU[-_#＃]?\s*[A-Za-z0-9]*\d)"
    r"|(?:#＃?\s*\d+)"
    r"|(?:HK\$|NT\$|US\$|RMB|[$¥￥])\s*\d"
    r"|(?:\d+(?:\.\d+)?\s*元)"
)
_CATALOG_HIT_RATIO = 0.3


def embed_texts(texts: list[str]) -> list[list[float] | None]:
    """Module-level embed seam (ADR 0047 §7).

    Tests may ``monkeypatch.setattr(document_ingest, "embed_texts", fn)`` —
    when unpatched this delegates to the live ``embeddings.embed_texts`` so
    monkeypatch teardown always restores real behavior (a plain
    ``from ... import embed_texts`` would permanently bind whatever function
    was installed on ``embeddings`` at first-import time).
    """
    return embeddings.embed_texts(texts)


def _cap_onnx_threads() -> None:
    """ADR 0047 §7 — cap ONNX/ORT intra-op threads (best-effort, env must be
    set before the fastembed model loads) so an ingest does not stall live
    turns on a 2–4-core on-prem box."""
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "ORT_NUM_THREADS"):
        os.environ.setdefault(var, "1")


def _attachment_embed_dedupe_key(attachment_id: uuid.UUID, embed_round: int) -> str:
    """Per-round dedupe: job dedupe keys are one-shot forever, so a cold-pass
    reschedule needs its own key — reusing the key would dead-end the row at
    ``ready_lexical`` (the old job's key already exists once it succeeds)."""
    return f"{ATTACHMENT_EMBED_KIND}:{attachment_id}:{embed_round}"


def _embed_reschedule_delay(embed_round: int) -> timedelta:
    return timedelta(
        seconds=min(
            _EMBED_RESCHEDULE_BASE_SECONDS * (embed_round + 1),
            _EMBED_RESCHEDULE_MAX_SECONDS,
        )
    )


async def _fetch_chunks(db: AsyncSession, attachment_id: uuid.UUID) -> list[DocumentChunk]:
    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.attachment_id == attachment_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return list(result.scalars().all())


def _guess_kind(blocks: list[DocumentBlock]) -> str:
    """Deterministic SKU/price-density heuristic — no LLM (ADR 0047 §5)."""
    lines: list[str] = []
    for block in blocks:
        if block.kind == "heading":
            continue
        for line in block.text.split("\n"):
            line = line.strip()
            if line:
                lines.append(line)
    if not lines:
        return "document"
    hits = sum(1 for line in lines if _CATALOG_LINE_RE.search(line))
    return "catalog" if hits / len(lines) >= _CATALOG_HIT_RATIO else "document"


def _build_doc_profile(filename: str, parsed: ParsedDocument, *, truncated: bool) -> dict:
    headings = [
        b.text.strip() for b in parsed.blocks if b.kind == "heading" and b.text and b.text.strip()
    ]
    first_body = next(
        (
            b.text.strip()
            for b in parsed.blocks
            if b.kind != "heading" and b.text and b.text.strip()
        ),
        "",
    )
    stem = Path(filename).stem.strip()
    title = headings[0] if headings else (stem or filename)
    pages = max((b.page or 0) for b in parsed.blocks) or 1
    return {
        "title": title,
        "pages": pages,
        "outline": headings,
        "kind_guess": _guess_kind(parsed.blocks),
        "preview": (first_body or title)[:200],
        "partial": bool(truncated),
    }


async def _mark_failed(db: AsyncSession, attachment: Attachment, exc: Exception) -> None:
    attachment.status = "failed"
    attachment.error = f"No readable text could be extracted — {exc}"
    await db.flush()
    logger.warning("attachment %s ingest failed: %s", attachment.id, exc)


async def _embed_missing_chunks(db: AsyncSession, chunks: list[DocumentChunk]) -> int:
    """Batched embed pass over chunks whose ``embedding`` is NULL.

    Returns the count of chunks still NULL after the pass. ``embed_texts``
    may yield per-item ``None`` (cold embedder) — those stay NULL.
    """
    model = embedding_model_name()
    pending = [c for c in chunks if c.embedding is None]
    for i in range(0, len(pending), _EMBED_BATCH):
        batch = pending[i : i + _EMBED_BATCH]
        # CPU-bound ONNX inference must not pin the worker event loop
        # (AGENTS.md review rule) — offload each batch to a thread.
        vectors = await asyncio.to_thread(embed_texts, [embed_text_for(c) for c in batch])
        for chunk, vec in zip(batch, vectors, strict=True):
            if vec:
                chunk.embedding = vec
                chunk.embedding_model = model
    await db.flush()
    return sum(1 for c in chunks if c.embedding is None)


async def _enqueue_embed_job(
    db: AsyncSession, attachment_id: uuid.UUID, *, embed_round: int, delay: timedelta | None = None
) -> None:
    await repos.enqueue_job(
        db,
        kind=ATTACHMENT_EMBED_KIND,
        payload={"attachment_id": str(attachment_id), "embed_round": embed_round},
        dedupe_key=_attachment_embed_dedupe_key(attachment_id, embed_round),
        run_after=datetime.now(UTC) + delay if delay is not None else None,
    )


async def _load_transcript(
    attachment_id: uuid.UUID,
) -> tuple[ParsedDocument, str | None] | None:
    """Read ``attachments/{id}/transcript.json`` → parsed blocks + engine
    provenance (ADR 0048 §3/§4). ``None`` when no transcript is stored yet —
    or when it is unreadable, in which case the caller falls back to the
    original bytes (a no-text file just re-parks at ``needs_ocr`` so the
    client can submit again)."""
    try:
        raw = await get_bytes(attachment_transcript_key(attachment_id))
    except (MediaStorageError, ClientError):
        return None
    try:
        payload = json.loads(raw)
        pages = [
            TranscriptPage(page=int(p["page"]), text=str(p["text"]))
            for p in payload.get("pages") or []
        ]
    except (KeyError, TypeError, ValueError):
        return None
    return parse_transcript(pages), payload.get("engine")


async def run_attachment_ingest(db: AsyncSession, *, attachment_id: uuid.UUID) -> None:
    """Parse → profile → chunk → embed one attachment (ADR 0047 §7)."""
    _cap_onnx_threads()
    attachment = await db.get(Attachment, attachment_id)
    if attachment is None:
        logger.warning("attachment_ingest: attachment %s not found", attachment_id)
        return

    existing = await _fetch_chunks(db, attachment_id)
    if attachment.status in ("ready_lexical", "ready") and existing:
        # At-least-once replay: chunks already landed — only (re)run the
        # embed pass; never duplicate chunk rows.
        nulls = await _embed_missing_chunks(db, existing)
        attachment.status = "ready" if nulls == 0 else "ready_lexical"
        if nulls:
            await _enqueue_embed_job(db, attachment_id, embed_round=0)
        await db.flush()
        return

    # ADR 0048 §4 — the stored transcript is the canonical parsed text for
    # an OCR'd doc. Detection is by existence, not status: the transcript
    # route re-parks the row at ``pending`` once it accepts text, and a
    # later re-chunk must still reuse the transcript rather than re-parse
    # bytes that have no text layer.
    loaded = await _load_transcript(attachment.id)
    from_transcript = loaded is not None
    parsed: ParsedDocument
    ocr_engine: str | None = None
    try:
        if loaded is not None:
            parsed, ocr_engine = loaded
        else:
            data = await get_bytes(attachment.object_key)
            parsed = parse_document(attachment.filename, data)
    except NoExtractableTextError as exc:
        # ADR 0048 §1 — a clean-but-empty document parks for OCR; it is not a
        # failure. The page count lets a client drive browser OCR.
        attachment.status = "needs_ocr"
        attachment.error = f"No readable text could be extracted — {exc}"
        attachment.doc_profile = {"pages": exc.page_count, "ocr": "pending"}
        await db.flush()
        logger.info("attachment %s parked at needs_ocr: %s", attachment.id, exc)
        return
    except Exception as exc:  # noqa: BLE001 — parser/storage raise many types;
        # all are deterministic file faults, never retryable job errors (§10).
        await _mark_failed(db, attachment, exc)
        return

    result = chunk_blocks(parsed.blocks, ChunkConfig())
    if not result.chunks:
        # Empty/heading-only input → nothing retrievable; reporting ``ready``
        # would lie to the UI (§10 — permanent, readable failure).
        await _mark_failed(db, attachment, ValueError("document contains no readable text"))
        return
    profile = _build_doc_profile(attachment.filename, parsed, truncated=result.truncated)
    if from_transcript:
        # ADR 0048 §5 — provenance marker for UI/grounding, never a trust
        # signal: ``engine`` is whatever the client claimed.
        profile["ocr"] = True
        if ocr_engine:
            profile["engine"] = ocr_engine

    if existing:
        await db.execute(delete(DocumentChunk).where(DocumentChunk.attachment_id == attachment_id))
    rows: list[DocumentChunk] = []
    for chunk in result.chunks:
        row = DocumentChunk(
            attachment_id=attachment.id,
            chunk_index=chunk.index,
            text=chunk.text,
            heading_path=chunk.heading_path or None,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
        )
        db.add(row)
        rows.append(row)
    await db.flush()

    attachment.doc_profile = profile
    attachment.error = None
    attachment.status = "ready_lexical"
    await db.flush()

    nulls = await _embed_missing_chunks(db, rows)
    if nulls == 0:
        attachment.status = "ready"
    else:
        await _enqueue_embed_job(db, attachment_id, embed_round=0)
    await db.flush()
    logger.info(
        "attachment %s ingested: chunks=%d null_vectors=%d status=%s",
        attachment_id,
        len(rows),
        nulls,
        attachment.status,
    )


async def run_attachment_embed(
    db: AsyncSession, *, attachment_id: uuid.UUID, embed_round: int = 0
) -> None:
    """Second-phase embed pass: fill NULL vectors, flip ``ready`` when done.

    ``embed_round`` counts cold-embedder reschedules (payload
    ``embed_round``); each follow-up gets a fresh dedupe key and a growing
    delay so a warming model isn't hammered, and after
    ``_EMBED_MAX_RESCHEDULES`` the row stays ``ready_lexical`` — honest
    partial readiness, not an infinite job burn.
    """
    _cap_onnx_threads()
    attachment = await db.get(Attachment, attachment_id)
    if attachment is None:
        logger.warning("attachment_embed: attachment %s not found", attachment_id)
        return
    if attachment.status == "failed":
        return

    chunks = await _fetch_chunks(db, attachment_id)
    if not chunks:
        return

    nulls = await _embed_missing_chunks(db, chunks)
    if nulls == 0:
        attachment.status = "ready"
        attachment.error = None
    else:
        attachment.status = "ready_lexical"
        if embed_round < _EMBED_MAX_RESCHEDULES:
            await _enqueue_embed_job(
                db,
                attachment_id,
                embed_round=embed_round + 1,
                delay=_embed_reschedule_delay(embed_round),
            )
        else:
            logger.warning(
                "attachment %s still has %d NULL vectors after %d embed rounds — "
                "staying ready_lexical",
                attachment_id,
                nulls,
                embed_round + 1,
            )
    await db.flush()
    logger.info(
        "attachment %s embed pass: null_vectors=%d status=%s",
        attachment_id,
        nulls,
        attachment.status,
    )
