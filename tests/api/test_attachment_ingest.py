"""API-tier tests for the ADR 0047 attachment ingest job.

The worker-side ingest module ``internal.memory.document_ingest`` does not
exist yet — imports stay inside helpers/test bodies so collection succeeds and
each test fails on the missing seam (ModuleNotFoundError / AttributeError /
assertion), never at collection time.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory import repos
from internal.memory.document_chunk import ChunkConfig
from tests.api.attachment_helpers import (
    ATTACHMENT_EMBED_KIND,
    ATTACHMENT_INGEST_KIND,
    active_embedding_model_name,
    attachment_embed_dedupe_key,
    attachment_ingest_dedupe_key,
    fetch_attachment,
    fetch_chunks,
    fetch_jobs,
    make_catalog_text,
    make_over_cap_text,
    make_pdf_with_outline,
    make_prose_text,
    make_scanned_pdf,
    none_embedder,
    patch_embedder,
    run_ingest,
    run_next_job,
    seed_pending_attachment,
    seed_session,
    warm_embedder,
)
from tests.api.helpers import register_user


async def _member_with_session(
    client: AsyncClient, db_session: AsyncSession
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    data = await register_user(client)
    user_id = uuid.UUID(data["user"]["id"])
    company_id = uuid.UUID(data["user"]["organizations"][0]["id"])
    session = await seed_session(db_session, user_id=user_id, company_id=company_id)
    return user_id, company_id, session.id


async def _seed_pdf(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    session_id: uuid.UUID,
    filename: str = "catalog2026.pdf",
    data: bytes | None = None,
) -> uuid.UUID:
    return await seed_pending_attachment(
        db_session,
        user_id=user_id,
        company_id=company_id,
        session_id=session_id,
        filename=filename,
        data=data if data is not None else make_pdf_with_outline(),
        content_type="application/pdf",
    )


@pytest.mark.asyncio
async def test_worker_dispatches_attachment_kinds() -> None:
    """ADR 0039: a new job type is one ``_JOB_HANDLERS`` entry."""
    from cmd.worker.main import _JOB_HANDLERS

    assert callable(_JOB_HANDLERS[ATTACHMENT_INGEST_KIND])
    assert callable(_JOB_HANDLERS[ATTACHMENT_EMBED_KIND])


@pytest.mark.asyncio
async def test_ingest_pdf_marks_ready_with_profile_and_chunks(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_embedder(monkeypatch, warm_embedder)
    user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await _seed_pdf(
        db_session, user_id=user_id, company_id=company_id, session_id=session_id
    )

    job = await run_next_job(db_session)
    assert job is not None and job.kind == ATTACHMENT_INGEST_KIND
    assert job.status == "succeeded"

    row = await fetch_attachment(db_session, attachment_id)
    assert row.status == "ready"
    assert row.error is None

    chunks = await fetch_chunks(db_session, attachment_id)
    assert chunks
    assert all(chunk.embedding is not None for chunk in chunks)
    model_name = active_embedding_model_name()
    assert all(chunk.embedding_model == model_name for chunk in chunks)
    assert {chunk.page_start for chunk in chunks} == {1, 2}
    assert all(chunk.page_end == chunk.page_start for chunk in chunks)
    assert any("Intro" in (chunk.heading_path or "") for chunk in chunks)
    assert any("Details" in (chunk.heading_path or "") for chunk in chunks)

    profile = row.doc_profile
    assert profile["title"]
    assert profile["pages"] == 2
    assert isinstance(profile["outline"], list) and profile["outline"]
    assert any("Intro" in str(entry) for entry in profile["outline"])
    assert any("Details" in str(entry) for entry in profile["outline"])
    assert profile["kind_guess"] in {"catalog", "document"}
    assert isinstance(profile["preview"], str) and profile["preview"]
    assert profile["partial"] is False


@pytest.mark.asyncio
async def test_ingest_kind_guess_reads_catalog_vs_document(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0047 §5: kind_guess is a deterministic SKU/price/table heuristic."""
    patch_embedder(monkeypatch, warm_embedder)
    user_id, company_id, session_id = await _member_with_session(client, db_session)
    catalog_id = await seed_pending_attachment(
        db_session,
        user_id=user_id,
        company_id=company_id,
        session_id=session_id,
        filename="pricelist.txt",
        data=make_catalog_text(),
        content_type="text/plain",
    )
    prose_id = await seed_pending_attachment(
        db_session,
        user_id=user_id,
        company_id=company_id,
        session_id=session_id,
        filename="about.md",
        data=make_prose_text(),
        content_type="text/markdown",
    )

    assert await run_next_job(db_session) is not None
    assert await run_next_job(db_session) is not None

    catalog = await fetch_attachment(db_session, catalog_id)
    prose = await fetch_attachment(db_session, prose_id)
    assert catalog.doc_profile["kind_guess"] == "catalog"
    assert prose.doc_profile["kind_guess"] == "document"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [make_scanned_pdf(), b"this is not a pdf document"],
    ids=["scanned", "corrupt"],
)
async def test_ingest_parse_failure_marks_failed_and_job_succeeds(
    client: AsyncClient, db_session: AsyncSession, data: bytes
) -> None:
    """ADR 0047 §10: parse failures are permanent — the handler swallows the
    parse error so a corrupt file never burns job retries."""
    user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await _seed_pdf(
        db_session,
        user_id=user_id,
        company_id=company_id,
        session_id=session_id,
        filename="menu-scan.pdf",
        data=data,
    )

    job = await run_next_job(db_session)
    assert job is not None and job.status == "succeeded"
    assert job.attempts == 1

    row = await fetch_attachment(db_session, attachment_id)
    assert row.status == "failed"
    assert row.error and "text" in row.error.lower()
    assert await fetch_chunks(db_session, attachment_id) == []


@pytest.mark.asyncio
async def test_cold_embedder_leaves_ready_lexical_and_enqueues_embed_job(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0047 §7: chunks left NULL keep the attachment at ``ready_lexical``
    and re-enqueue an embed job — a non-blocking embedder must not flip ready."""
    patch_embedder(monkeypatch, none_embedder)
    user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await _seed_pdf(
        db_session, user_id=user_id, company_id=company_id, session_id=session_id
    )

    job = await run_next_job(db_session)
    assert job is not None and job.status == "succeeded"

    row = await fetch_attachment(db_session, attachment_id)
    assert row.status == "ready_lexical"
    chunks = await fetch_chunks(db_session, attachment_id)
    assert chunks
    assert all(chunk.embedding is None for chunk in chunks)

    embed_jobs = await fetch_jobs(db_session, kind=ATTACHMENT_EMBED_KIND)
    assert len(embed_jobs) == 1
    assert embed_jobs[0].status == "pending"
    assert embed_jobs[0].payload.get("attachment_id") == str(attachment_id)
    assert embed_jobs[0].dedupe_key == attachment_embed_dedupe_key(attachment_id)


@pytest.mark.asyncio
async def test_embed_job_fills_vectors_and_marks_ready(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_embedder(monkeypatch, none_embedder)
    user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await _seed_pdf(
        db_session, user_id=user_id, company_id=company_id, session_id=session_id
    )
    await run_next_job(db_session)
    row = await fetch_attachment(db_session, attachment_id)
    assert row.status == "ready_lexical"

    patch_embedder(monkeypatch, warm_embedder)
    embed_job = await run_next_job(db_session)
    assert embed_job is not None and embed_job.kind == ATTACHMENT_EMBED_KIND
    assert embed_job.status == "succeeded"

    row = await fetch_attachment(db_session, attachment_id)
    assert row.status == "ready"
    chunks = await fetch_chunks(db_session, attachment_id)
    model_name = active_embedding_model_name()
    assert chunks
    assert all(chunk.embedding is not None for chunk in chunks)
    assert all(chunk.embedding_model == model_name for chunk in chunks)


@pytest.mark.asyncio
async def test_over_cap_ingests_capped_prefix_and_marks_partial(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0047 §10: over-cap ingests the first N chunks and says so."""
    patch_embedder(monkeypatch, warm_embedder)
    user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await seed_pending_attachment(
        db_session,
        user_id=user_id,
        company_id=company_id,
        session_id=session_id,
        filename="catalog-huge.txt",
        data=make_over_cap_text(),
        content_type="text/plain",
    )

    await run_next_job(db_session)

    row = await fetch_attachment(db_session, attachment_id)
    chunks = await fetch_chunks(db_session, attachment_id)
    assert len(chunks) == ChunkConfig().max_chunks == 150
    assert [chunk.chunk_index for chunk in chunks] == list(range(ChunkConfig().max_chunks))
    assert row.doc_profile["partial"] is True
    assert row.status in {"ready_lexical", "ready"}


@pytest.mark.asyncio
async def test_ingest_rerun_does_not_duplicate_chunks(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0039 is at-least-once — a replayed ingest must stay idempotent."""
    patch_embedder(monkeypatch, warm_embedder)
    user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await _seed_pdf(
        db_session, user_id=user_id, company_id=company_id, session_id=session_id
    )

    await run_ingest(db_session, attachment_id)
    first = await fetch_chunks(db_session, attachment_id)
    await run_ingest(db_session, attachment_id)
    second = await fetch_chunks(db_session, attachment_id)

    assert first
    assert len(second) == len(first)
    assert [chunk.chunk_index for chunk in second] == [chunk.chunk_index for chunk in first]
    assert [chunk.text for chunk in second] == [chunk.text for chunk in first]


@pytest.mark.asyncio
async def test_ingest_job_dedupes_per_attachment(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await _seed_pdf(
        db_session, user_id=user_id, company_id=company_id, session_id=session_id
    )

    dupe = await repos.enqueue_job(
        db_session,
        kind=ATTACHMENT_INGEST_KIND,
        payload={"attachment_id": str(attachment_id)},
        dedupe_key=attachment_ingest_dedupe_key(attachment_id),
    )
    assert dupe is None
    jobs = await fetch_jobs(db_session, kind=ATTACHMENT_INGEST_KIND)
    assert len(jobs) == 1

    job = await run_next_job(db_session)
    assert job is not None and job.status == "succeeded"


@pytest.mark.asyncio
async def test_cold_embedder_reschedules_fresh_embed_job(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cold pass must enqueue a *new* runnable job — reusing the current
    job's one-shot dedupe key dead-ends the attachment at ``ready_lexical``
    forever (the row's key already exists once its job succeeded)."""
    patch_embedder(monkeypatch, none_embedder)
    user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await _seed_pdf(
        db_session, user_id=user_id, company_id=company_id, session_id=session_id
    )
    await run_next_job(db_session)  # ingest → ready_lexical + embed job :0

    embed_job = await run_next_job(db_session)  # cold pass again
    assert embed_job is not None and embed_job.kind == ATTACHMENT_EMBED_KIND
    assert embed_job.status == "succeeded"

    embed_jobs = await fetch_jobs(db_session, kind=ATTACHMENT_EMBED_KIND)
    assert len(embed_jobs) == 2, "cold pass must schedule a follow-up, not collide"
    assert embed_jobs[1].status == "pending"
    assert embed_jobs[1].dedupe_key != embed_jobs[0].dedupe_key

    # When the embedder warms, the follow-up completes the job.
    patch_embedder(monkeypatch, warm_embedder)
    from tests.api.attachment_helpers import run_embed

    await run_embed(db_session, attachment_id)
    row = await fetch_attachment(db_session, attachment_id)
    assert row.status == "ready"
    assert all(c.embedding is not None for c in await fetch_chunks(db_session, attachment_id))


@pytest.mark.asyncio
async def test_cold_embedder_stops_rescheduling_after_cap(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A permanently-cold embedder must not loop forever — after the
    reschedule cap the row stays honestly ``ready_lexical`` (lexical
    retrieval still works), not ``ready`` and not a job-queue burn."""
    patch_embedder(monkeypatch, none_embedder)
    user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await _seed_pdf(
        db_session, user_id=user_id, company_id=company_id, session_id=session_id
    )
    await run_next_job(db_session)

    from internal.memory.document_ingest import _EMBED_MAX_RESCHEDULES
    from tests.api.attachment_helpers import run_embed

    for embed_round in range(_EMBED_MAX_RESCHEDULES + 2):
        await run_embed(db_session, attachment_id, embed_round=embed_round)

    embed_jobs = await fetch_jobs(db_session, kind=ATTACHMENT_EMBED_KIND)
    assert len(embed_jobs) <= _EMBED_MAX_RESCHEDULES + 1
    row = await fetch_attachment(db_session, attachment_id)
    assert row.status == "ready_lexical"


@pytest.mark.asyncio
async def test_empty_document_marks_failed_not_ready(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero-byte / heading-only input yields no chunks — that is a permanent
    ``failed`` with readable error (§10), never a false ``ready`` with no
    retrievable text."""
    patch_embedder(monkeypatch, warm_embedder)
    user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await seed_pending_attachment(
        db_session,
        user_id=user_id,
        company_id=company_id,
        session_id=session_id,
        filename="notes.txt",
        data=b"",
        content_type="text/plain",
    )

    job = await run_next_job(db_session)
    assert job is not None and job.status == "succeeded"  # no retry burn

    row = await fetch_attachment(db_session, attachment_id)
    assert row.status == "failed"
    assert row.error and "text" in row.error.lower()
    assert await fetch_chunks(db_session, attachment_id) == []


@pytest.mark.asyncio
async def test_embed_runs_off_worker_event_loop(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AGENTS.md review rule: CPU-bound ONNX inference inside async handlers
    runs in a worker thread — a warm embed must never pin the loop."""
    import threading

    loop_ident = threading.get_ident()
    seen: list[int] = []

    def spy(texts: list[str]) -> list[list[float] | None]:
        seen.append(threading.get_ident())
        return [None] * len(texts)

    patch_embedder(monkeypatch, spy)
    user_id, company_id, session_id = await _member_with_session(client, db_session)
    attachment_id = await _seed_pdf(
        db_session, user_id=user_id, company_id=company_id, session_id=session_id
    )

    await run_ingest(db_session, attachment_id)
    assert seen, "embed seam was never called"
    assert all(ident != loop_ident for ident in seen)
