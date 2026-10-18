"""Document chunk retrieve for the ``read_attachment`` tool (ADR 0047 §6/§9/§14).

Hybrid retrieve scoped to **one** attachment's chunks (≤150 → exact scan,
§9): lexical ``strpos`` candidates are narrowed in SQL and scored in Python,
pgvector ``cosine_distance`` gives the vector list, and the two fuse by
reciprocal rank (RRF_K=60). ``section`` slices by ``heading_path`` and works
while every embedding is still NULL (``ready_lexical``, §7).

Refusals return ``None`` — unknown, cross-company and out-of-scope ids are
indistinguishable so existence never leaks across tenants (§14). Owner scope
is re-checked on every call: ``session``/``user`` rows need a ``user_id``
match; ``org`` rows are readable by every company member.
"""

from __future__ import annotations

import asyncio
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from internal.memory import embeddings
from internal.memory.embeddings import embedding_model_name
from internal.memory.models import Attachment, DocumentChunk

RRF_K = 60
# Candidate pool pulled from pgvector for RRF fusion (final list is slice-capped).
VECTOR_TOP_K = 20
# ADR 0047 §6 — read_attachment returns at most 5 slices.
SLICE_CAP = 5


def embed_query(text: str) -> list[float] | None:
    """Module-level query-embed seam (same style as ``document_ingest.embed_texts``).

    Tests may ``monkeypatch.setattr(document_retrieve, "embed_query", fn)`` —
    when unpatched this delegates to ``embeddings.embed_query`` so teardown
    always restores real behavior.
    """
    return embeddings.embed_query(text)


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip()).lower()


def _visible_to_member(
    attachment: Attachment | None, *, company_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    """ADR 0047 §14 owner matrix — re-checked on every call, never trusted."""
    if attachment is None or attachment.company_id != company_id:
        return False
    if attachment.owner_scope == "org":
        return True
    # session | user scope: the uploader only (unknown scopes refuse too).
    return attachment.user_id == user_id


def _lexical_score(text: str, qn: str) -> float:
    """Normalized hit ratio over raw ``text`` — denser needle coverage wins.

    ``strpos`` in SQL already narrowed candidates to substring hits; scoring
    stays in Python (product_retrieve ``_lexical_hits`` style).
    """
    tl = (text or "").lower()
    if not qn or qn not in tl:
        return 0.0
    hits = tl.count(qn)
    return hits * len(qn) / max(len(tl), 1)


def _lexical_hits(rows: list[DocumentChunk], qn: str) -> list[DocumentChunk]:
    scored = [(c, _lexical_score(c.text, qn)) for c in rows]
    ranked = [(s, c) for c, s in scored if s > 0]
    ranked.sort(key=lambda t: (-t[0], t[1].chunk_index))
    return [c for _, c in ranked]


def _rrf_merge(*ranked_lists: list[DocumentChunk]) -> list[DocumentChunk]:
    """Reciprocal-rank fusion (K=60): a chunk hit by both lists outranks a
    pure-vector tie; ties break on list-hit count then ``chunk_index`` so the
    order is deterministic."""
    rrf: dict[uuid.UUID, float] = {}
    lists_hit: dict[uuid.UUID, int] = {}
    by_id: dict[uuid.UUID, DocumentChunk] = {}
    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked, start=1):
            cid = chunk.id
            rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (RRF_K + rank)
            lists_hit[cid] = lists_hit.get(cid, 0) + 1
            by_id.setdefault(cid, chunk)
    return sorted(
        by_id.values(),
        key=lambda c: (-rrf[c.id], -lists_hit[c.id], c.chunk_index),
    )


def _last_heading(heading_path: str | None) -> str:
    if not heading_path:
        return ""
    return heading_path.split(" > ")[-1].strip()


def _slice_ref(chunk: DocumentChunk, *, fallback: str) -> str:
    """ADR 0047 §4 ref shape: ``p.{page} · {heading}``, page or heading alone
    when the other half is missing, else the attachment filename — always
    non-empty."""
    heading = _last_heading(chunk.heading_path)
    page_ref = ""
    if chunk.page_start is not None:
        page_ref = f"p.{chunk.page_start}"
        if chunk.page_end is not None and chunk.page_end != chunk.page_start:
            page_ref = f"p.{chunk.page_start}–{chunk.page_end}"
    if page_ref and heading:
        return f"{page_ref} · {heading}"
    return page_ref or heading or fallback


def _to_slice(chunk: DocumentChunk, *, filename: str) -> dict:
    fallback = filename.strip() or f"chunk {chunk.chunk_index + 1}"
    return {
        "chunk_id": str(chunk.id),
        "ref": _slice_ref(chunk, fallback=fallback),
        "text": chunk.text,
    }


async def _lexical_candidates(
    db: AsyncSession, *, attachment_id: uuid.UUID, qn: str
) -> list[DocumentChunk]:
    stmt = (
        select(DocumentChunk)
        .options(defer(DocumentChunk.embedding))
        .where(DocumentChunk.attachment_id == attachment_id)
        .where(func.strpos(func.lower(DocumentChunk.text), qn) > 0)
    )
    return list((await db.scalars(stmt)).all())


async def _vector_candidates(
    db: AsyncSession, *, attachment_id: uuid.UUID, query: str
) -> list[DocumentChunk]:
    vec = await asyncio.to_thread(embed_query, query)
    if vec is None:
        return []
    dist = DocumentChunk.embedding.cosine_distance(vec).label("cosine_dist")
    stmt = (
        select(DocumentChunk, dist)
        .options(defer(DocumentChunk.embedding))
        .where(DocumentChunk.attachment_id == attachment_id)
        .where(DocumentChunk.embedding.isnot(None))
        # §9: two embedding spaces never share — the active model filter is
        # mandatory even when a foreign-model vector would be a perfect hit.
        .where(DocumentChunk.embedding_model == embedding_model_name())
        .order_by(dist)
        .limit(VECTOR_TOP_K)
    )
    return [chunk for chunk, _d in (await db.execute(stmt)).all()]


async def _query_chunks(
    db: AsyncSession, *, attachment_id: uuid.UUID, query: str
) -> list[DocumentChunk]:
    qn = _norm(query)
    if not qn:
        return []
    lexical = _lexical_hits(await _lexical_candidates(db, attachment_id=attachment_id, qn=qn), qn)
    vector = await _vector_candidates(db, attachment_id=attachment_id, query=query)
    return _rrf_merge(lexical, vector)


async def _section_chunks(
    db: AsyncSession, *, attachment_id: uuid.UUID, section: str
) -> list[DocumentChunk]:
    stmt = (
        select(DocumentChunk)
        .options(defer(DocumentChunk.embedding))
        .where(DocumentChunk.attachment_id == attachment_id)
        .where(func.strpos(func.lower(DocumentChunk.heading_path), _norm(section)) > 0)
        .order_by(DocumentChunk.chunk_index)
        .limit(SLICE_CAP)
    )
    return list((await db.scalars(stmt)).all())


async def read_document(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    attachment_id: uuid.UUID,
    query: str | None = None,
    section: str | None = None,
) -> dict | None:
    """Slice one attachment for the ``read_attachment`` tool (ADR 0047 §6).

    Returns ``{"slices": [{chunk_id, ref, text}], "partial": bool}`` capped at
    5 slices, or ``None`` for unknown / out-of-scope ids and param-less calls.
    """
    try:
        att_id = (
            attachment_id if isinstance(attachment_id, uuid.UUID) else uuid.UUID(str(attachment_id))
        )
    except (ValueError, TypeError, AttributeError):
        return None

    attachment = await db.get(Attachment, att_id)
    if not _visible_to_member(attachment, company_id=company_id, user_id=user_id):
        return None

    q = (query or "").strip()
    s = (section or "").strip()
    if not q and not s:
        return None
    if q:
        chunks = await _query_chunks(db, attachment_id=attachment.id, query=q)
    else:
        chunks = await _section_chunks(db, attachment_id=attachment.id, section=s)

    return {
        "slices": [_to_slice(c, filename=attachment.filename) for c in chunks[:SLICE_CAP]],
        "partial": attachment.status != "ready",
    }
