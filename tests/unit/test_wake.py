"""ADR 0058 — wake-hint primitives: trigger wait, kick endpoint, drain loop."""

from __future__ import annotations

import asyncio

import pytest

from internal.memory import wake


@pytest.mark.asyncio
async def test_wait_for_trigger_wake_consumes_flag() -> None:
    stop, wk = asyncio.Event(), asyncio.Event()
    wk.set()
    assert await wake.wait_for_trigger(stop, wk, 10) == "wake"
    assert not wk.is_set()


@pytest.mark.asyncio
async def test_wait_for_trigger_sweep_on_timeout() -> None:
    stop, wk = asyncio.Event(), asyncio.Event()
    assert await wake.wait_for_trigger(stop, wk, 0.05) == "sweep"


@pytest.mark.asyncio
async def test_wait_for_trigger_stop_wins() -> None:
    stop, wk = asyncio.Event(), asyncio.Event()
    stop.set()
    assert await wake.wait_for_trigger(stop, wk, 10) == "stop"


async def _asgi_call(
    app, method: str, path: str, body: bytes = b""
) -> tuple[int, bytes]:
    sent = []
    inbound = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        return inbound.pop(0) if inbound else {"type": "http.disconnect"}

    async def send(msg) -> None:
        sent.append(msg)

    await app({"type": "http", "method": method, "path": path}, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m["body"] for m in sent if m["type"] == "http.response.body")
    return status, body


@pytest.mark.asyncio
async def test_kick_app_accepts_post_kick_only() -> None:
    fired = []
    app = wake.make_kick_app(lambda: fired.append(1))

    status, _ = await _asgi_call(app, "POST", "/kick")
    assert status == 202
    assert fired == [1]

    # A stray body is drained and ignored — never parsed (ADR 0058 §6).
    status, _ = await _asgi_call(app, "POST", "/kick", body=b'{"job_id": 1}')
    assert status == 202
    assert len(fired) == 2

    status, _ = await _asgi_call(app, "GET", "/kick")
    assert status == 404
    status, _ = await _asgi_call(app, "POST", "/kick/123")
    assert status == 404
    status, _ = await _asgi_call(app, "POST", "/other")
    assert status == 404
    assert len(fired) == 2


def test_database_url_to_dsn_strips_dialect() -> None:
    dsn = wake.database_url_to_dsn(
        "postgresql+asyncpg://u:p@h:5432/db?ssl=require"
    )
    assert dsn == "postgresql://u:p@h:5432/db?ssl=require"


@pytest.mark.asyncio
async def test_drain_loop_hint_mid_claim_triggers_extra_pass() -> None:
    """Lost-wakeup rule: the flag is cleared BEFORE each claim attempt —
    a hint landing mid-claim must cause one more pass (ADR 0058 §7)."""
    from cmd.worker.main import _drain_loop

    stop, wk = asyncio.Event(), asyncio.Event()
    calls = 0

    async def fake_claim(_worker_id):
        nonlocal calls
        calls += 1
        assert not wk.is_set()  # cleared before claim — never eaten
        if calls >= 3:
            stop.set()
        else:
            wk.set()  # a hint arrives "during" the drain
        return False, None

    await _drain_loop(
        "test-worker",
        stop,
        wk,
        lane_active=lambda: True,
        claim=fake_claim,
        hint_gap_seconds=0.01,
    )
    assert calls == 3


@pytest.mark.asyncio
async def test_drain_loop_fallback_reclaim_gated_at_60s(
    monkeypatch, tmp_path
) -> None:
    """No lane → today's cadence: backoff poll + reclaim only every 60s."""
    from cmd.worker import main as worker_mod
    from internal.config import settings

    monkeypatch.setattr(settings, "worker_poll_seconds", 0.01)
    reclaims = []
    monkeypatch.setattr(
        worker_mod,
        "_reclaim_sweep",
        lambda: reclaims.append(1) or asyncio.sleep(0),
    )

    stop, wk = asyncio.Event(), asyncio.Event()
    calls = 0

    async def fake_claim(_worker_id):
        nonlocal calls
        calls += 1
        if calls >= 4:
            stop.set()
        return False, None

    await worker_mod._drain_loop(
        "test-worker",
        stop,
        wk,
        lane_active=lambda: False,
        claim=fake_claim,
    )
    assert calls == 4
    assert len(reclaims) == 1  # the loop-top 60s check fires once, not per tick
