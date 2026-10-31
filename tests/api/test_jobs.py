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
    from cmd.worker.main import _claim_and_run

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

    ran, _due_in = await _claim_and_run("test-worker")
    assert ran is True

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
    from cmd.worker.main import _claim_and_run

    async with session_factory() as db:
        job = await repos.enqueue_job(db, kind="nope", dedupe_key="tick:unknown", max_attempts=1)
        job_id = job.id
        await db.commit()

    ran, _due_in = await _claim_and_run("test-worker")
    assert ran is True

    async with session_factory() as db:
        done = await db.get(Job, job_id)
        assert done is not None
        assert done.status == "failed"
        assert "unknown job kind" in (done.error or "")


# --- ADR 0058 — commit-bound wake hints (pg_notify + HTTP kick) -----------


async def _listen_jobs(dsn: str):
    """Raw asyncpg LISTEN — the same shape the worker's ListenLane uses."""
    import asyncpg

    from internal.memory import wake

    conn = await asyncpg.connect(wake.database_url_to_dsn(dsn))
    notes = []
    await conn.add_listener("jobs", lambda *args: notes.append(args))
    return conn, notes


async def _wait_notes(notes: list, n: int, timeout: float = 3.0) -> int:
    deadline = asyncio.get_running_loop().time() + timeout
    while len(notes) < n and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.05)
    return len(notes)


@pytest.mark.asyncio
async def test_enqueue_emits_one_notify_per_commit(
    db_session, test_database_url
) -> None:
    """Two enqueues in one txn → exactly one pg_notify at commit."""
    conn, notes = await _listen_jobs(test_database_url)
    try:
        await repos.enqueue_job(db_session, kind="hot_search", dedupe_key="n:1")
        await repos.enqueue_job(db_session, kind="promote_signals", dedupe_key="n:2")
        assert notes == []  # nothing fires before commit
        await db_session.commit()
        assert await _wait_notes(notes, 1) == 1

        # Dedupe no-op lands nothing → silent.
        await repos.enqueue_job(db_session, kind="hot_search", dedupe_key="n:1")
        await db_session.commit()
        await asyncio.sleep(0.3)
        assert len(notes) == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_rollback_emits_no_notify(db_session, test_database_url) -> None:
    conn, notes = await _listen_jobs(test_database_url)
    try:
        await repos.enqueue_job(db_session, kind="hot_search", dedupe_key="rb:1")
        await db_session.rollback()
        await asyncio.sleep(0.3)
        assert notes == []
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_savepoint_rollback_emits_no_notify(
    db_session, test_database_url
) -> None:
    """Marks are txn-scoped by clearing: a savepoint rollback clears all —
    the outer job's hint is dropped rather than leaked (sweep covers it)."""
    conn, notes = await _listen_jobs(test_database_url)
    try:
        job = await repos.enqueue_job(db_session, kind="hot_search", dedupe_key="sp:outer")
        sp = await db_session.begin_nested()
        await repos.enqueue_job(db_session, kind="hot_search", dedupe_key="sp:inner")
        await sp.rollback()
        await db_session.commit()
        await asyncio.sleep(0.5)
        assert notes == []
        await db_session.refresh(job)
        assert job.status == "pending"  # outer row still landed
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_kick_fires_only_after_commit(db_session, monkeypatch) -> None:
    """after_commit kicks fire-and-forget; rollback kicks never fire."""
    from internal.config import settings
    from internal.memory import wake

    kicks: list[str] = []

    async def fake_post(_client, url: str) -> None:
        kicks.append(url)

    monkeypatch.setattr(wake, "_post_kick", fake_post)
    monkeypatch.setattr(settings, "worker_kick_url", "http://worker.internal")
    monkeypatch.setattr(settings, "scheduler_kick_url", "http://sched.internal")

    await repos.enqueue_job(db_session, kind="hot_search", dedupe_key="k:1")
    assert kicks == []
    await db_session.commit()
    for _ in range(40):
        if kicks:
            break
        await asyncio.sleep(0.05)
    assert kicks == ["http://worker.internal/kick"]

    await repos.enqueue_job(db_session, kind="hot_search", dedupe_key="k:2")
    await db_session.rollback()
    await asyncio.sleep(0.1)
    assert len(kicks) == 1

    # Instance-settings write kicks the scheduler (ADR 0050 apply preserved).
    await repos.upsert_instance_settings(db_session, email_backend="smtp")
    await db_session.commit()
    for _ in range(40):
        if len(kicks) > 1:
            break
        await asyncio.sleep(0.05)
    assert kicks[-1] == "http://sched.internal/kick"


@pytest.mark.asyncio
async def test_claim_and_run_reports_due_in_on_db_clock(
    session_factory, worker_db
) -> None:
    """Empty claim returns the deferred job's due delay for the due-timer."""
    from cmd.worker.main import _claim_and_run

    async with session_factory() as db:
        await repos.enqueue_job(
            db,
            kind="hot_search",
            dedupe_key="due:1",
            run_after=datetime.now(UTC) + timedelta(seconds=600),
        )
        await db.commit()

    ran, due_in = await _claim_and_run("test-worker")
    assert ran is False
    assert due_in is not None
    assert 550 < due_in <= 600

    async with session_factory() as db:
        rows = (await db.scalars(select(Job).where(Job.status == "pending"))).all()
        assert len(rows) == 1  # nothing claimed, nothing queued twice
