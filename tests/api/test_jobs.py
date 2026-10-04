"""Postgres job queue (ADR 0039): dedupe, SKIP LOCKED claim, backoff, reclaim."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from internal.memory import repos
from internal.memory.models import Job


@pytest.fixture
def worker_db(session_factory):
    """Point the worker's open_session() factory at the test database."""
    from internal.memory.database import set_session_factory

    set_session_factory(session_factory)
    yield
    set_session_factory(None)


@pytest.mark.asyncio
async def test_enqueue_job_dedupe_key_returns_none_on_conflict(db_session) -> None:
    first = await repos.enqueue_job(
        db_session, kind="hot_search", dedupe_key="hot_search:bucket-1"
    )
    assert first is not None
    second = await repos.enqueue_job(
        db_session, kind="hot_search", dedupe_key="hot_search:bucket-1"
    )
    assert second is None
    await db_session.commit()
    rows = (await db_session.scalars(select(Job))).all()
    assert len(rows) == 1
    assert rows[0].status == "pending"
    assert rows[0].payload == {}


@pytest.mark.asyncio
async def test_claim_next_job_concurrent_claims_are_distinct(session_factory) -> None:
    """Two concurrent claims must take two different jobs — never the same one."""
    async with session_factory() as db:
        for key in ("claim:a", "claim:b"):
            await repos.enqueue_job(db, kind="hot_search", dedupe_key=key)
        await db.commit()

    async def claim(worker_id: str) -> Job | None:
        async with session_factory() as db:
            job = await repos.claim_next_job(db, worker_id=worker_id)
            await db.commit()
            return job

    first, second = await asyncio.gather(claim("w1"), claim("w2"))
    assert first is not None
    assert second is not None
    assert first.id != second.id
    assert {first.locked_by, second.locked_by} == {"w1", "w2"}
    assert first.status == second.status == "running"
    assert first.attempts == second.attempts == 1

    async with session_factory() as db:
        assert await repos.claim_next_job(db, worker_id="w3") is None


@pytest.mark.asyncio
async def test_claim_next_job_skips_uncommitted_lock(session_factory) -> None:
    """SKIP LOCKED: a second claimer ignores a row locked by an open transaction."""
    async with session_factory() as db:
        for key in ("skip:a", "skip:b"):
            await repos.enqueue_job(db, kind="hot_search", dedupe_key=key)
        await db.commit()

    async with session_factory() as s1:
        first = await repos.claim_next_job(s1, worker_id="w1")
        assert first is not None
        async with session_factory() as s2:
            # s1's UPDATE is uncommitted — the row lock must make it invisible.
            second = await repos.claim_next_job(s2, worker_id="w2")
            assert second is not None
            assert second.id != first.id
            await s2.commit()
        await s1.commit()


@pytest.mark.asyncio
async def test_finish_job_retry_backoff_then_failed(db_session) -> None:
    await repos.enqueue_job(
        db_session, kind="hot_search", dedupe_key="retry:1", max_attempts=3
    )
    await db_session.commit()

    claimed = await repos.claim_next_job(db_session, worker_id="w1")
    assert claimed is not None
    assert claimed.attempts == 1
    assert claimed.locked_by == "w1"

    before = datetime.now(UTC)
    await repos.finish_job(db_session, claimed, ok=False, error="boom")
    assert claimed.status == "pending"
    assert claimed.run_after > before
    assert claimed.error == "boom"
    assert claimed.locked_by is None
    await db_session.commit()

    # Backoff: run_after is in the future so the job is not claimable yet.
    assert await repos.claim_next_job(db_session, worker_id="w1") is None

    # Last allowed attempt -> terminal failed.
    claimed.attempts = claimed.max_attempts
    await repos.finish_job(db_session, claimed, ok=False, error="boom again")
    await db_session.commit()
    assert claimed.status == "failed"
    assert claimed.error == "boom again"


@pytest.mark.asyncio
async def test_reclaim_stale_jobs_returns_lease_to_pending(db_session) -> None:
    stale = await repos.enqueue_job(db_session, kind="hot_search", dedupe_key="stale:1")
    fresh = await repos.enqueue_job(db_session, kind="promote_signals", dedupe_key="stale:2")
    await db_session.commit()
    for job in (stale, fresh):
        job.status = "running"
        job.locked_by = "dead-worker"
    stale.locked_at = datetime.now(UTC) - timedelta(minutes=30)
    fresh.locked_at = datetime.now(UTC)
    await db_session.commit()

    reclaimed = await repos.reclaim_stale_jobs(db_session, older_than_minutes=15)
    await db_session.commit()
    assert reclaimed == 1

    await db_session.refresh(stale)
    await db_session.refresh(fresh)
    assert stale.status == "pending"
    assert stale.locked_by is None
    assert fresh.status == "running"
    assert fresh.locked_by == "dead-worker"


@pytest.mark.asyncio
async def test_worker_tick_runs_hot_search_job_to_success(
    session_factory, worker_db, monkeypatch
) -> None:
    """Enqueue -> one worker tick -> succeeded (handlers stubbed)."""
    from cmd.worker.main import _run_one_job

    async def fake_hot_search(db):
        return {"google_trends_hk": 3, "errors": 0}

    async def fake_rss(db):
        return {"google_news_hk": 2, "errors": 0}

    monkeypatch.setattr("cmd.worker.main.ingest_hot_search", fake_hot_search)
    monkeypatch.setattr("cmd.worker.main.ingest_rss_news", fake_rss)

    async with session_factory() as db:
        job = await repos.enqueue_job(db, kind="hot_search", dedupe_key="tick:1")
        job_id = job.id
        await db.commit()

    assert await _run_one_job("test-worker") is True

    async with session_factory() as db:
        done = await db.get(Job, job_id)
        assert done is not None
        assert done.status == "succeeded"
        assert done.locked_by == "test-worker"
        assert done.attempts == 1


@pytest.mark.asyncio
async def test_worker_tick_marks_unknown_kind_failed(
    session_factory, worker_db
) -> None:
    from cmd.worker.main import _run_one_job

    async with session_factory() as db:
        job = await repos.enqueue_job(db, kind="nope", dedupe_key="tick:unknown", max_attempts=1)
        job_id = job.id
        await db.commit()

    assert await _run_one_job("test-worker") is True

    async with session_factory() as db:
        done = await db.get(Job, job_id)
        assert done is not None
        assert done.status == "failed"
        assert "unknown job kind" in (done.error or "")
