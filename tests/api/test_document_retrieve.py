"""API-tier tests for the ADR 0047 document retrieve service (§6, §9, §14).

The seam ``internal.memory.document_retrieve`` does not exist yet — imports
stay inside helpers/test bodies so collection succeeds and each test fails on
the missing module (ModuleNotFoundError), never at collection time.

Pinned invented contract
------------------------
``async def read_document(db, *, company_id, user_id, attachment_id,
query=None, section=None) -> dict | None``

- Returns ``{"slices": [{"chunk_id", "ref", "text"}, ...], "partial": bool}``
  with at most 5 slices (ADR 0047 §6 — the ``read_attachment`` tool shape).
- ``chunk_id`` is the ``DocumentChunk`` uuid rendered as a string — a
  grounding id next to ``source_signal_ids`` / ``product_context_ids`` (§11).
- ``ref`` renders from ``heading_path`` + page per §4 ("p.3 · 優惠詳情"):
  tests pin that it carries ``p.{page}`` when the chunk is paged and the
  heading text when it is under a heading (a paged chunk under a heading
  carries both). Always a non-empty string.
- ``partial`` is True while vectors are still filling
  (``status == "ready_lexical"``, §7); False once ``ready``.
- ``query`` runs hybrid lexical (``strpos`` on raw ``text`` — heading words
  must not hit every chunk in a section, §4) + pgvector + RRF over this
  attachment's chunks only (≤150 → exact scan, §9). The vector pass only
  sees chunks whose ``embedding_model`` matches the active model.
- ``section`` slices by ``heading_path`` and works before any vector exists.
- Refusal shape: ``None`` — unknown and out-of-scope ids are
  indistinguishable so existence never leaks across tenants (chosen over
  raising, so the tool degrades to "no such attachment" rather than an
  exception crossing the LLM boundary). §14: ``company_id`` and owner scope
  are re-checked on every call — ``session``/``user`` scope requires a
  ``user_id`` match; ``org`` scope is readable by every company member.
- Query embedding goes through a module-level ``embed_query``/``embed_texts``
  lookup (same seam style as ``document_ingest.embed_texts``) — patched via
  ``patch_query_embedder``.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api.attachment_helpers import (
    active_embedding_model_name,
    fetch_attachment,
    fetch_chunks,
    make_long_section_markdown,
    make_offer_markdown,
    make_pdf_with_outline,
    none_embedder,
    patch_embedder,
    patch_query_embedder,
    run_embed,
    run_ingest,
    seed_pending_attachment,
    seed_session,
    uniform_query_vector,
    warm_embedder,
)
from tests.api.helpers import join_org, register_user


async def _member_with_session(
    client: AsyncClient, db_session: AsyncSession
) -> tuple[dict, uuid.UUID, uuid.UUID, uuid.UUID]:
    data = await register_user(client)
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    session = await seed_session(db_session, user_id=user_id, company_id=company_id)
    return data, user_id, company_id, session.id


async def _read_document(
    db_session: AsyncSession,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    attachment_id: uuid.UUID,
    query: str | None = None,
    section: str | None = None,
) -> dict | None:
    """Call the invented seam — deferred import so the missing module, not
    collection, is what fails."""
    from internal.memory.document_retrieve import read_document

    return await read_document(
        db_session,
        company_id=company_id,
        user_id=user_id,
        attachment_id=attachment_id,
        query=query,
        section=section,
    )


async def _seed_offer_doc(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    session_id: uuid.UUID,
) -> uuid.UUID:
    """The CJK offer doc — .md because the pdfium fixtures are ASCII-only."""
    return await seed_pending_attachment(
        db_session,
        user_id=user_id,
        company_id=company_id,
        session_id=session_id,
        filename="offers.md",
        data=make_offer_markdown(),
        content_type="text/markdown",
    )


# --- query path ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_returns_needle_slice_with_heading_ref(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0047 §6: query → ≤5 slices of {chunk_id, ref, text}; the top slice
    is the chunk containing the query term (deterministic under strpos —
    lexical hits must rank above pure vector ties)."""
    patch_embedder(monkeypatch, warm_embedder)
    patch_query_embedder(monkeypatch, lambda _q: uniform_query_vector())
    _data, user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await _seed_offer_doc(
        db_session, user_id=user_id, company_id=company_id, session_id=session_id
    )
    await run_ingest(db_session, attachment_id)
    assert (await fetch_attachment(db_session, attachment_id)).status == "ready"

    result = await _read_document(
        db_session,
        company_id=company_id,
        user_id=user_id,
        attachment_id=attachment_id,
        query="優惠期",
    )

    assert result is not None
    slices = result["slices"]
    assert 1 <= len(slices) <= 5
    by_id = {str(c.id): c for c in await fetch_chunks(db_session, attachment_id)}
    for s in slices:
        # Grounding id: the DocumentChunk uuid as a string.
        assert s["chunk_id"] in by_id
        assert isinstance(s["ref"], str) and s["ref"].strip()
        assert isinstance(s["text"], str) and s["text"].strip()
    top = by_id[slices[0]["chunk_id"]]
    assert "優惠期" in top.text
    # md chunks have no page — the ref carries the heading text instead (§4).
    assert "優惠詳情" in slices[0]["ref"]
    assert result["partial"] is False


@pytest.mark.asyncio
async def test_slice_ref_includes_page_for_paged_doc(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0047 §4: refs render "p.N · heading" for paged chunks — the page
    half is pinned here (the heading half in the md query test)."""
    patch_embedder(monkeypatch, warm_embedder)
    patch_query_embedder(monkeypatch, lambda _q: uniform_query_vector())
    _data, user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await seed_pending_attachment(
        db_session,
        user_id=user_id,
        company_id=company_id,
        session_id=session_id,
        filename="catalog2026.pdf",
        data=make_pdf_with_outline(),
        content_type="application/pdf",
    )
    await run_ingest(db_session, attachment_id)

    result = await _read_document(
        db_session,
        company_id=company_id,
        user_id=user_id,
        attachment_id=attachment_id,
        query="Page two body",
    )

    assert result is not None
    assert result["slices"]
    top = result["slices"][0]
    by_id = {str(c.id): c for c in await fetch_chunks(db_session, attachment_id)}
    assert "Page two body" in by_id[top["chunk_id"]].text
    assert "p.2" in top["ref"]


@pytest.mark.asyncio
async def test_query_vector_path_filters_embedding_model(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0047 §9: every retrieve filters the active ``embedding_model`` —
    a foreign-model chunk is excluded even when its vector is the strongest
    possible hit (exact match to the query vector)."""
    patch_embedder(monkeypatch, warm_embedder)
    query_vec = uniform_query_vector()
    patch_query_embedder(monkeypatch, lambda _q: query_vec)
    _data, user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await _seed_offer_doc(
        db_session, user_id=user_id, company_id=company_id, session_id=session_id
    )
    await run_ingest(db_session, attachment_id)

    chunks = await fetch_chunks(db_session, attachment_id)
    foreign = chunks[0]
    foreign.embedding = query_vec
    foreign.embedding_model = "foreign-model-v0"
    await db_session.commit()

    result = await _read_document(
        db_session,
        company_id=company_id,
        user_id=user_id,
        attachment_id=attachment_id,
        query="zzq-no-lexical-hit",
    )

    assert result is not None
    slices = result["slices"]
    assert slices, "the vector pass should still hit active-model chunks"
    active = active_embedding_model_name()
    by_id = {str(c.id): c for c in chunks}
    for s in slices:
        assert s["chunk_id"] != str(foreign.id)
        assert by_id[s["chunk_id"]].embedding_model == active


# --- section path -------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_slices_work_without_vectors(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0047 §6/§7: section slices by heading path serve while every
    embedding is still NULL (``ready_lexical``) — and the result says so."""
    patch_embedder(monkeypatch, none_embedder)
    _data, user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await _seed_offer_doc(
        db_session, user_id=user_id, company_id=company_id, session_id=session_id
    )
    await run_ingest(db_session, attachment_id)
    row = await fetch_attachment(db_session, attachment_id)
    assert row.status == "ready_lexical"
    chunks = await fetch_chunks(db_session, attachment_id)
    assert all(c.embedding is None for c in chunks)

    result = await _read_document(
        db_session,
        company_id=company_id,
        user_id=user_id,
        attachment_id=attachment_id,
        section="優惠詳情",
    )

    assert result is not None
    assert result["partial"] is True
    slices = result["slices"]
    assert slices
    by_id = {str(c.id): c for c in chunks}
    for s in slices:
        assert "優惠詳情" in (by_id[s["chunk_id"]].heading_path or "")


@pytest.mark.asyncio
async def test_partial_flag_tracks_attachment_status(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0047 §7: partial=True while vectors fill, False once ``ready``."""
    patch_embedder(monkeypatch, none_embedder)
    _data, user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await _seed_offer_doc(
        db_session, user_id=user_id, company_id=company_id, session_id=session_id
    )
    await run_ingest(db_session, attachment_id)

    result = await _read_document(
        db_session,
        company_id=company_id,
        user_id=user_id,
        attachment_id=attachment_id,
        section="優惠詳情",
    )
    assert result is not None and result["partial"] is True

    patch_embedder(monkeypatch, warm_embedder)
    await run_embed(db_session, attachment_id)
    assert (await fetch_attachment(db_session, attachment_id)).status == "ready"

    result = await _read_document(
        db_session,
        company_id=company_id,
        user_id=user_id,
        attachment_id=attachment_id,
        section="優惠詳情",
    )
    assert result is not None and result["partial"] is False


@pytest.mark.asyncio
async def test_slices_capped_at_five(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0047 §6: a section with more than 5 matching chunks returns
    exactly 5 slices."""
    patch_embedder(monkeypatch, none_embedder)
    _data, user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await seed_pending_attachment(
        db_session,
        user_id=user_id,
        company_id=company_id,
        session_id=session_id,
        filename="offers-long.md",
        data=make_long_section_markdown(),
        content_type="text/markdown",
    )
    await run_ingest(db_session, attachment_id)
    chunks = await fetch_chunks(db_session, attachment_id)
    matching = [c for c in chunks if "優惠詳情" in (c.heading_path or "")]
    assert len(matching) > 5, "fixture must exceed the slice cap to test it"

    result = await _read_document(
        db_session,
        company_id=company_id,
        user_id=user_id,
        attachment_id=attachment_id,
        section="優惠詳情",
    )

    assert result is not None
    assert len(result["slices"]) == 5
    by_id = {str(c.id): c for c in chunks}
    for s in result["slices"]:
        assert "優惠詳情" in (by_id[s["chunk_id"]].heading_path or "")


# --- tenant + owner scope (§14, COLLECT §6) ------------------------------------


@pytest.mark.asyncio
async def test_read_refuses_cross_company_attachment(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """COLLECT §6 / ADR 0047 §14: an attachment from company B is
    indistinguishable from a missing id under company A credentials — the
    owner's own read succeeds first so a missing seam can't pass as refusal."""
    patch_embedder(monkeypatch, none_embedder)
    _data_a, user_a, company_a, _session_a = await _member_with_session(client, db_session)
    other = await register_user(client)
    user_b = uuid.UUID(other["user"]["id"])
    company_b = uuid.UUID(other["user"]["organizations"][0]["id"])
    session_b = await seed_session(db_session, user_id=user_b, company_id=company_b)
    attachment_id = await seed_pending_attachment(
        db_session,
        user_id=user_b,
        company_id=company_b,
        session_id=session_b.id,
        filename="offers.md",
        data=make_offer_markdown(),
        content_type="text/markdown",
    )
    await run_ingest(db_session, attachment_id)

    own = await _read_document(
        db_session,
        company_id=company_b,
        user_id=user_b,
        attachment_id=attachment_id,
        query="優惠期",
    )
    assert own is not None and own["slices"]

    refused = await _read_document(
        db_session,
        company_id=company_a,
        user_id=user_a,
        attachment_id=attachment_id,
        query="優惠期",
    )
    assert refused is None


@pytest.mark.asyncio
async def test_read_refuses_session_scratch_of_other_member(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0047 §14 owner scope: session scratch is the uploader's — another
    member of the same company gets ``None`` for a session-scoped id."""
    patch_embedder(monkeypatch, none_embedder)
    _data, user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await _seed_offer_doc(
        db_session, user_id=user_id, company_id=company_id, session_id=session_id
    )
    await run_ingest(db_session, attachment_id)

    other = await register_user(client)
    other_id = uuid.UUID(other["user"]["id"])
    await join_org(db_session, user_id=other_id, company_id=company_id)

    refused = await _read_document(
        db_session,
        company_id=company_id,
        user_id=other_id,
        attachment_id=attachment_id,
        query="優惠期",
    )
    assert refused is None


@pytest.mark.asyncio
async def test_org_scope_attachment_readable_by_any_member(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner matrix (§14 decided): ``org`` scope is shared read-only across
    the company — no ``user_id`` match required."""
    patch_embedder(monkeypatch, none_embedder)
    _data, _user_id, company_id, _session_id = await _member_with_session(client, db_session)
    other = await register_user(client)
    other_id = uuid.UUID(other["user"]["id"])
    await join_org(db_session, user_id=other_id, company_id=company_id)
    attachment_id = await seed_pending_attachment(
        db_session,
        user_id=None,
        company_id=company_id,
        session_id=None,
        filename="offers.md",
        data=make_offer_markdown(),
        content_type="text/markdown",
        owner_scope="org",
    )
    await run_ingest(db_session, attachment_id)

    result = await _read_document(
        db_session,
        company_id=company_id,
        user_id=other_id,
        attachment_id=attachment_id,
        query="優惠期",
    )
    assert result is not None and result["slices"]


@pytest.mark.asyncio
async def test_read_unknown_attachment_returns_none(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Refusal shape pin: a well-formed but unknown id returns ``None``,
    not an exception."""
    _data, user_id, company_id, _session_id = await _member_with_session(client, db_session)
    result = await _read_document(
        db_session,
        company_id=company_id,
        user_id=user_id,
        attachment_id=uuid.uuid4(),
        query="優惠期",
    )
    assert result is None
