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

Invented contract the retrieve step must satisfy (see test_document_retrieve.py
for the full pinned seam):
- ``internal.memory.document_retrieve.read_document(db, *, company_id,
  user_id, attachment_id, query=None, section=None)`` → ``{"slices": [...],
  "partial": bool}`` or ``None`` for out-of-scope ids.
- query embedding goes through a module-level ``embed_query``/``embed_texts``
  lookup so tests can monkeypatch it (same seam style as
  ``document_ingest.embed_texts``).

Invented contract the session-wiring step must satisfy (see
test_session_attachment_wiring.py for the full pinned seam):
- ``PostMessageRequest.attachment_ids: list[uuid.UUID]`` — each id must be
  this session's scratch (``attachment_sessions`` join or ``session_id``) or
  the member's ``user``/``org`` library row; unknown / cross-tenant /
  out-of-scope ids → 404 (existence never leaks).
- The persisted user message stores ``metadata["attachment_ids"]`` (the
  ``MESSAGE_ATTACHMENT_IDS_KEY`` constant) as a list of uuid strings, and
  ``MessageResponse`` gains an ``attachments`` digest-chip list
  ``[{id, filename, status}]``.
- ``session.state["attachments"]`` holds hydrated digests
  ``{id, filename, status, doc_profile subset}`` per ADR 0047 §5/§13.
- ``POST /api/attachments/{id}/save`` — save-to-library is HTTP (§2): flips
  the caller's own session-scratch row to ``owner_scope="user"``; unknown /
  cross-company / non-owner → 404; re-save → 200 (idempotent).
- ``StubSessionGraph`` — the deterministic ``set_session_graph`` seam for
  POST /messages without LLM keys (see class docstring).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from types import SimpleNamespace

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


def make_offer_markdown() -> bytes:
    """Markdown doc with a ``優惠詳情`` section whose body mentions ``優惠期``.

    CJK section docs go through the md parser — the pdfium fixtures are
    ASCII-only. Lands as ~3 chunks: one under ``產品目錄``, one under
    ``產品目錄 > 優惠詳情`` (the 優惠期 needle), one under ``產品目錄 > 條款及細則``.
    """
    return (
        "# 產品目錄\n\n"
        "本店招牌奶茶系列，每日新鮮沖調。\n\n"
        "## 優惠詳情\n\n"
        "優惠期由即日起至二零二六年三月三十一日，會員購買指定飲品可享九折優惠。\n\n"
        "## 條款及細則\n\n"
        "所有價格以港元計算，優惠不可與其他折扣同時使用。\n"
    ).encode()


def make_long_section_markdown(paragraphs: int = 7) -> bytes:
    """One ``優惠詳情`` section with enough paragraphs to exceed the slice cap.

    Every paragraph is its own document block (~60 chars each — under the
    chunk budget, so one chunk per paragraph), giving ``paragraphs`` chunks
    under the same heading path.
    """
    parts = ["# 產品目錄", "", "## 優惠詳情", ""]
    for i in range(paragraphs):
        parts.append(
            f"優惠條款第{i + 1}項：會員於推廣期內購買指定飲品可享折扣優惠，"
            "每張收據限用一次，詳情請向店員查詢，優惠受條款及細則約束。"
        )
        parts.append("")
    parts.extend(["## 條款及細則", "", "所有價格以港元計算。"])
    return "\n".join(parts).encode()


# --- DB seeding -------------------------------------------------------------


async def seed_session(db: AsyncSession, *, user_id: uuid.UUID, company_id: uuid.UUID) -> Session:
    session = Session(user_id=user_id, company_id=company_id, mode="CHAT", state={})
    db.add(session)
    await db.flush()
    return session


async def seed_pending_attachment(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    company_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
    filename: str,
    data: bytes,
    content_type: str,
    owner_scope: str = "session",
) -> uuid.UUID:
    """Seed the upload seam: object bytes + pending row + session join + ingest job.

    ``owner_scope`` pins the ADR 0047 §2 ownership matrix for retrieve tests:
    ``session`` scratch and ``user`` library rows carry ``user_id``; ``org``
    rows are readable by every company member (pass ``session_id=None`` and
    ``user_id=None`` for a pure org row — the session join is then skipped).
    """
    from internal.media.storage import put_bytes

    attachment_id = uuid.uuid4()
    object_key = f"attachments/{attachment_id}/{filename}"
    await put_bytes(key=object_key, data=data, content_type=content_type)
    db.add(
        Attachment(
            id=attachment_id,
            company_id=company_id,
            owner_scope=owner_scope,
            user_id=user_id,
            session_id=session_id,
            filename=filename,
            content_type=content_type,
            object_key=object_key,
            status="pending",
            doc_profile={},
        )
    )
    if session_id is not None:
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


def patch_query_embedder(
    monkeypatch: pytest.MonkeyPatch,
    fn: Callable[[str], list[float] | None],
) -> None:
    """Patch the query-side embedder wherever the retrieve seam may look it up.

    ``fn`` takes one query string and returns one vector or ``None``
    (``embed_query`` shape). ``embed_texts`` names are patched too so an impl
    that embeds via the batch seam is still intercepted. Same dual-site style
    as ``patch_embedder``: ``internal.memory.embeddings`` covers module-attr
    call sites; ``document_retrieve.<name>`` covers ``from ... import``
    bindings (``raising=False`` — the module need not export both names).
    """
    from internal.memory import embeddings

    def _batch(texts: list[str]) -> list[list[float] | None]:
        return [fn(t) for t in texts]

    monkeypatch.setattr(embeddings, "embed_query", fn)
    monkeypatch.setattr(embeddings, "embed_texts", _batch)
    try:
        from internal.memory import document_retrieve
    except ImportError:
        return
    monkeypatch.setattr(document_retrieve, "embed_query", fn, raising=False)
    monkeypatch.setattr(document_retrieve, "embed_texts", _batch, raising=False)


def uniform_query_vector() -> list[float]:
    """The warm_embedder vector — cosine distance 0 to every warm chunk."""
    return [0.001 * (i + 1) for i in range(EMBEDDING_DIM)]


async def read_document_for_member(
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    attachment_id: uuid.UUID,
    query: str | None = None,
    section: str | None = None,
) -> dict | None:
    """Open-session call of the invented ``read_document`` seam (sync BDD steps).

    Deferred import: ``internal.memory.document_retrieve`` does not exist yet —
    tests fail on the ModuleNotFoundError, never at collection.
    """
    from internal.memory.document_retrieve import read_document

    async with open_session() as db:
        return await read_document(
            db,
            company_id=company_id,
            user_id=user_id,
            attachment_id=attachment_id,
            query=query,
            section=section,
        )


# --- session wiring seams (ADR 0047 §2/§3/§5/§13) ------------------------------

# Invented names (documented in test_session_attachment_wiring.py):
MESSAGE_ATTACHMENT_IDS_KEY = "attachment_ids"
"""metadata key on the persisted user message row: ``[str(attachment_id)]``."""

MESSAGE_ATTACHMENTS_FIELD = "attachments"
"""``MessageResponse`` digest-chip field: ``[{id, filename, status}]``."""

STATE_ATTACHMENTS_KEY = "attachments"
"""``session.state`` digest list — hydrated from the ``attachment_sessions``
join per ADR 0047 §13: ``{id, filename, status, doc_profile subset}``."""

SAVE_ATTACHMENT_PATH = "/api/attachments/{attachment_id}/save"
"""Save-to-library route (§2) — POST flips the caller's scratch row to
``owner_scope="user"`` and returns the updated ``AttachmentOut``."""

# Fields a state digest must carry beyond id/filename/status — any one of the
# doc_profile subset keys satisfies the §5 "digests only" contract.
DIGEST_PROFILE_KEYS = ("title", "preview", "pages", "outline", "kind_guess", "doc_profile")


class StubSessionGraph:
    """Deterministic stand-in for the compiled session graph.

    ``set_session_graph(StubSessionGraph())`` lets POST /messages run a real
    turn without LLM keys: ``ainvoke`` echoes the ``graph_input`` state dict
    (optionally appending a canned assistant reply to ``messages``) so every
    key the service put on the input — including future ``attachments``
    digests — flows back into ``values``; ``aget_state`` reports the echoed
    values with ``next=()`` (never parked, never interrupted). ``last_input``
    records the exact ``graph_input`` for assertions.

    Matches the seam ``internal.session.service._invoke_graph`` /
    ``session_park_kind`` use: ``await graph.ainvoke(input, config)`` → dict,
    ``await graph.aget_state(config)`` → snapshot with ``.values`` and
    ``.next``. The conftest ``clean_db`` fixture resets it per test.
    """

    def __init__(self, reply: str | None = None) -> None:
        self.reply = reply
        self.last_input: dict | None = None
        self._values: dict = {}

    async def ainvoke(self, graph_input, config):
        self.last_input = graph_input
        values = dict(graph_input or {})
        if self.reply is not None:
            values["messages"] = [
                *(values.get("messages") or []),
                {"role": "assistant", "content": self.reply},
            ]
        self._values = values
        return values

    async def aget_state(self, config):
        return SimpleNamespace(values=dict(self._values), next=())


async def fetch_session_row(session_id: uuid.UUID) -> Session | None:
    """Open-session ``sessions`` row fetch — ``None`` after delete."""
    async with open_session() as db:
        return await db.get(Session, session_id)


async def fetch_attachment_or_none(attachment_id: uuid.UUID) -> Attachment | None:
    """Open-session ``attachments`` row fetch — ``None`` after GC/delete."""
    async with open_session() as db:
        return await db.get(Attachment, attachment_id)


async def list_attachment_rows(
    *,
    user_id: uuid.UUID | None = None,
    owner_scope: str | None = None,
    company_id: uuid.UUID | None = None,
) -> list[Attachment]:
    """Open-session attachment listing with optional scope/owner filters."""
    async with open_session() as db:
        stmt = select(Attachment).order_by(Attachment.created_at)
        if user_id is not None:
            stmt = stmt.where(Attachment.user_id == user_id)
        if owner_scope is not None:
            stmt = stmt.where(Attachment.owner_scope == owner_scope)
        if company_id is not None:
            stmt = stmt.where(Attachment.company_id == company_id)
        return list((await db.scalars(stmt)).all())


async def fetch_join_rows(
    attachment_id: uuid.UUID, *, session_id: uuid.UUID | None = None
) -> list[AttachmentSession]:
    """``attachment_sessions`` rows for an attachment (optionally one session)."""
    async with open_session() as db:
        stmt = select(AttachmentSession).where(
            AttachmentSession.attachment_id == attachment_id
        )
        if session_id is not None:
            stmt = stmt.where(AttachmentSession.session_id == session_id)
        return list((await db.scalars(stmt)).all())


async def fetch_chunk_count(attachment_id: uuid.UUID) -> int:
    async with open_session() as db:
        return len(await fetch_chunks(db, attachment_id))


async def read_object_bytes(key: str) -> bytes | None:
    """``get_bytes`` or ``None`` on ``MediaStorageError`` — backend-agnostic
    'are the object bytes gone' probe for GC assertions."""
    from internal.media.storage import MediaStorageError, get_bytes

    try:
        return await get_bytes(key)
    except MediaStorageError:
        return None


# --- read_attachment tool seams (ADR 0047 §5/§6/§14) ------------------------------
#
# Invented names the chat-tool step must satisfy (mirrored in
# tests/unit/test_read_attachment_tool.py,
# tests/unit/test_session_chat_attachments.py and the zero-instruction
# step defs in tests/api/bdd/step_defs/test_attachments.py):
#
# - ``internal.session.harness.read_attachment`` — async Pydantic AI tool fn
#   ``(ctx: RunContext[ChatDeps], attachment_id: str, query: str | None = None,
#   section: str | None = None) -> ReadAttachmentResponse``. Registered on the
#   chat agent; ``CHAT_TOOL_NAMES`` gains ``"read_attachment"`` and stays
#   disjoint from ``PUBLISH_TOOL_NAMES``.
# - ``schemas.tools.ReadAttachmentSlice {chunk_id: str, ref: str, text: str}``
#   and ``schemas.tools.ReadAttachmentResponse {slices: [ReadAttachmentSlice],
#   partial: bool, error: str | None}`` — the ONLY fields the LLM ever sees
#   (§5: digests + slices, never doc_profile / full document text).
# - ``ChatDeps`` gains ``user_id: uuid.UUID | None`` and a per-turn counter
#   ``attachment_reads: int``; ``harness.MAX_ATTACHMENT_READS_PER_TURN = 3``
#   pins the ADR "≤2–3 calls per turn" cap — call #4 in one turn returns an
#   error whose string contains ``"budget"`` (chosen: ``"budget_exceeded"``).
# - ``harness.read_document`` — module-level seam the tool invokes, signature
#   mirroring ``document_retrieve.read_document`` (same monkeypatchable style
#   as ``document_ingest.embed_texts`` / ``document_retrieve.embed_query``).
# - Refusals never raise: ``slices=[]`` + non-empty ``error`` for seam
#   refusals (unknown/out-of-scope id → ``None``), a call with neither
#   ``query`` nor ``section`` (chosen: refused before the seam), an
#   unparsable ``attachment_id``, and a missing session-db context.

READ_ATTACHMENT_TOOL = "read_attachment"
"""Pydantic AI tool name — ``CHAT_TOOL_NAMES`` member, never a publish tool."""

MAX_ATTACHMENT_READS = 3
"""Chosen per-turn budget (ADR 0047 §6 "≤2–3 calls"); the impl pins the same
cap as ``harness.MAX_ATTACHMENT_READS_PER_TURN``."""

PAYLOAD_ATTACHMENTS_KEY = "attachments"
"""``_chat_stream`` JSON payload key for the per-turn digest list:
``[{id, filename, title, kind_guess, status, partial}]`` (§5/§13)."""

FULL_TEXT_SENTINEL = "FULL-TEXT-LEAK-SENTINEL-全文外洩照出嚟"
"""Canary planted in a fake state-digest field a correct ``_chat_stream``
must never forward: the prompt carries digest fields only, never raw
document/chunk text (§5)."""


def model_prompt_text(messages) -> str:
    """Flatten every string ``part.content`` of a pydantic-ai ModelMessage
    list — the FunctionModel probe for what the agent actually saw."""
    texts: list[str] = []
    for message in messages or []:
        for part in getattr(message, "parts", []) or []:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                texts.append(content)
    return "\n".join(texts)


def make_digest_probe_model(
    *,
    filename: str,
    title: str,
    reply: str,
    seen: dict,
    sentinel: str = FULL_TEXT_SENTINEL,
):
    """FunctionModel + stream_function pair for ``set_chat_model_override``.

    The model emits ``reply`` ONLY when the prompt it was served carries the
    attachment digest (``"attachments"`` key + ``filename`` + ``title``) and
    no ``sentinel`` full-text leak — otherwise a ``MISSING-DIGEST`` marker,
    so assertions stay red until ``_chat_stream`` wires digests in (§5).
    ``seen`` records what the model observed for Then-step assertions.
    """
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel

    def _decide(messages) -> str:
        blob = model_prompt_text(messages)
        seen["prompt_text"] = blob
        seen["saw_attachments_key"] = f'"{PAYLOAD_ATTACHMENTS_KEY}"' in blob
        seen["saw_filename"] = filename in blob
        seen["saw_title"] = title in blob
        seen["saw_full_text"] = sentinel in blob
        if (
            seen["saw_attachments_key"]
            and seen["saw_filename"]
            and seen["saw_title"]
            and not seen["saw_full_text"]
        ):
            return reply
        return "MISSING-DIGEST-SENTINEL"

    def fn(messages, agent_info):
        return ModelResponse(parts=[TextPart(content=_decide(messages))])

    async def stream_fn(messages, agent_info):
        yield _decide(messages)

    return FunctionModel(fn, stream_function=stream_fn)


def make_read_attachment_driver(
    *,
    calls: list[dict],
    returns_seen: list,
    final_text: str,
):
    """FunctionModel that issues ``read_attachment`` ToolCallParts — one per
    model invocation until ``calls`` is exhausted — recording every
    ToolReturnPart content into ``returns_seen`` before emitting
    ``final_text``. Deterministic, sequential calls so per-turn budgets are
    observable."""
    import json as _json

    from pydantic_ai.messages import (
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
    )
    from pydantic_ai.models.function import DeltaToolCall, FunctionModel

    seen_ids: set[str] = set()

    def _decide(messages) -> tuple[str, dict | None]:
        for message in messages or []:
            for part in getattr(message, "parts", []) or []:
                if (
                    isinstance(part, ToolReturnPart)
                    and part.tool_call_id not in seen_ids
                ):
                    seen_ids.add(part.tool_call_id)
                    returns_seen.append(str(part.content))
        idx = len(returns_seen)
        if idx < len(calls):
            return ("tool", calls[idx])
        return ("text", None)

    def fn(messages, agent_info):
        kind, call = _decide(messages)
        if kind == "tool":
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=READ_ATTACHMENT_TOOL,
                        args=dict(call),
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content=final_text)])

    async def stream_fn(messages, agent_info):
        kind, call = _decide(messages)
        if kind == "tool":
            yield {
                0: DeltaToolCall(
                    name=READ_ATTACHMENT_TOOL,
                    json_args=_json.dumps(call),
                )
            }
        else:
            yield final_text

    return FunctionModel(fn, stream_function=stream_fn)


def patch_read_document_seam(monkeypatch: pytest.MonkeyPatch, stub) -> None:
    """Patch the ``read_document`` seam wherever the chat tool may look it up
    (same dual-site style as ``patch_query_embedder``): ``harness.read_document``
    covers a module-level binding the tool calls directly;
    ``document_retrieve.read_document`` covers a ``from ... import`` /
    module-attribute call site. Both use ``raising=False`` — either binding
    may legitimately be the only one an impl defines."""
    try:
        from internal.session import harness
    except ImportError:
        pass
    else:
        monkeypatch.setattr(harness, "read_document", stub, raising=False)
    try:
        from internal.memory import document_retrieve
    except ImportError:
        return
    monkeypatch.setattr(document_retrieve, "read_document", stub, raising=False)
