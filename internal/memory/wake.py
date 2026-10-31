"""ADR 0058 — commit-bound wake hints (pg_notify + HTTP kick).

Two lanes share one contract: they only wake the drain loop. The jobs row
remains the source of truth and the slow sweep stays the backstop.

Producers mark the DB session inside ``enqueue_job`` /
``upsert_instance_settings``; session-level hooks (registered in
``database.py``) emit the hints bound to commit:

- ``before_commit``: one ``pg_notify('jobs', '')`` per transaction
- ``after_commit``: fire-and-forget ``POST {url}/kick`` per marked service
- rollback paths clear all marks — a rolled-back txn leaks no hint

Consumers (``cmd.worker serve``, ``cmd.scheduler`` quiet mode) hold a
LISTEN lane (always-on Postgres) and/or a kick listener (any
environment). Neither is required for delivery — the sweep always runs.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Callable

import asyncpg
import httpx
import uvicorn
from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.config import settings

logger = logging.getLogger(__name__)

JOBS_CHANNEL = "jobs"

_NOTIFY_KEY = "wake_notify_jobs"
_KICKS_KEY = "wake_kick_services"

_KICK_URLS = {"worker": "worker_kick_url", "scheduler": "scheduler_kick_url"}


def _sync_session(db) -> Session:
    return getattr(db, "sync_session", db)


def mark_job_enqueued(db) -> None:
    """Job row landed this txn → notify once + kick the worker on commit."""
    info = _sync_session(db).info
    info[_NOTIFY_KEY] = True
    info.setdefault(_KICKS_KEY, set()).add("worker")


def mark_settings_changed(db) -> None:
    """Instance settings write this txn → kick the scheduler on commit."""
    _sync_session(db).info.setdefault(_KICKS_KEY, set()).add("scheduler")


def before_commit(session: Session) -> None:
    """One notification per committing transaction — never one per row."""
    if session.info.pop(_NOTIFY_KEY, None):
        session.execute(text("select pg_notify(:ch, '')"), {"ch": JOBS_CHANNEL})


def after_commit(session: Session) -> None:
    session.info.pop(_NOTIFY_KEY, None)
    services = session.info.pop(_KICKS_KEY, None)
    if services:
        _fire_kicks(services)


def after_rollback(session: Session, *_args) -> None:
    session.info.pop(_NOTIFY_KEY, None)
    session.info.pop(_KICKS_KEY, None)


_kick_tasks: set[asyncio.Task] = set()
_KICK_BACKOFF_SECONDS = (1.0, 5.0)
_kick_client: httpx.AsyncClient | None = None


def _kick_http() -> httpx.AsyncClient:
    global _kick_client
    if _kick_client is None:
        _kick_client = httpx.AsyncClient()
    return _kick_client


async def _post_kick(client: httpx.AsyncClient, url: str) -> None:
    for attempt, delay in enumerate((0.0, *_KICK_BACKOFF_SECONDS)):
        if delay:
            await asyncio.sleep(delay)
        try:
            await client.post(url, timeout=10.0)
            return
        except httpx.HTTPError as exc:
            if attempt == len(_KICK_BACKOFF_SECONDS):
                logger.warning("kick to %s failed after retries: %s", url, exc)


def _fire_kicks(services: set[str]) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for service in services:
        url = getattr(settings, _KICK_URLS[service])
        if not url:
            continue
        task = loop.create_task(
            _post_kick(_kick_http(), url.rstrip("/") + "/kick")
        )
        _kick_tasks.add(task)
        task.add_done_callback(_kick_tasks.discard)


async def wait_for_trigger(
    stop: asyncio.Event, wake: asyncio.Event, delay: float
) -> str:
    """Sleep until stop | wake | timeout. Returns 'stop'|'wake'|'sweep'."""
    stop_task = asyncio.ensure_future(stop.wait())
    wake_task = asyncio.ensure_future(wake.wait())
    try:
        done, _pending = await asyncio.wait(
            {stop_task, wake_task},
            timeout=delay,
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for task in (stop_task, wake_task):
            task.cancel()
    if stop_task in done:
        return "stop"
    if wake_task in done:
        # Consume the hint on wake — callers still clear before their next
        # work item (lost-wakeup rule), so this never eats a live flag.
        wake.clear()
        return "wake"
    return "sweep"


def make_kick_app(wake_cb: Callable[[], None]):
    """ASGI app: `POST /kick` only — no body, no params, ever (ADR 0058 §6)."""

    async def app(scope, receive, send):
        ok = (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and scope["path"] == "/kick"
        )
        if ok:
            wake_cb()
        # Drain the request body — kicks carry none, but ASGI requires
        # consumption so the connection stays clean for keep-alive reuse.
        if scope["type"] == "http":
            while True:
                message = await receive()
                if message["type"] == "http.disconnect" or not message.get(
                    "more_body"
                ):
                    break
        await send(
            {
                "type": "http.response.start",
                "status": 202 if ok else 404,
                "headers": [],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    return app


async def serve_kick(
    port: int, wake_cb: Callable[[], None]
) -> tuple[uvicorn.Server, asyncio.Task]:
    """Kick listener — holds no DB session; internal ingress is the boundary.

    Returns ``(server, serve_task)``; callers set ``server.should_exit`` and
    await the task to shut down.
    """
    server = uvicorn.Server(
        uvicorn.Config(
            make_kick_app(wake_cb),
            host="0.0.0.0",
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    task = asyncio.create_task(server.serve())
    return server, task


def database_url_to_dsn(url: str) -> str:
    """`postgresql+asyncpg://…` → raw asyncpg DSN (SSL query params pass through)."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


class ListenLane:
    """Raw asyncpg LISTEN connection — never borrowed from the SQLAlchemy
    pool (``pool_recycle`` would retire it). Capability-tested at start and
    re-probed on every sweep: transaction-mode poolers and dead conns both
    fail the loopback and degrade to kick-only/fallback."""

    def __init__(
        self,
        dsn: str,
        wake: asyncio.Event,
        *,
        channel: str = JOBS_CHANNEL,
        probe_timeout: float = 20.0,
        connect_timeout: float = 15.0,
    ) -> None:
        self.dsn = dsn
        self.channel = channel
        self.wake = wake
        self.probe_timeout = probe_timeout
        self.connect_timeout = connect_timeout
        self.conn: asyncpg.Connection | None = None
        self._probe_event = asyncio.Event()

    @property
    def alive(self) -> bool:
        return self.conn is not None and not self.conn.is_closed()

    async def start(self) -> bool:
        try:
            conn = await asyncpg.connect(self.dsn, timeout=self.connect_timeout)
            await conn.add_listener(self.channel, self._on_notify)
            conn.add_termination_listener(self._on_terminate)
            sock = conn._transport.get_extra_info("socket")
            if sock is not None:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            if not await self._probe(conn):
                await conn.close()
                logger.warning("LISTEN lane loopback failed (pooler?); disabling")
                return False
            self.conn = conn
            logger.info("LISTEN lane up on channel %s", self.channel)
            return True
        except (TimeoutError, OSError, asyncpg.Error):
            logger.exception("LISTEN lane failed to start")
            return False

    def _on_notify(self, *_args) -> None:
        self.wake.set()
        self._probe_event.set()

    def _on_terminate(self, *_args) -> None:
        if self.conn is not None:
            logger.warning("LISTEN connection terminated; lane down until next sweep")
        self.conn = None

    async def probe(self) -> bool:
        if not self.alive:
            return False
        return await self._probe(self.conn)

    async def _probe(self, conn: asyncpg.Connection) -> bool:
        """Loopback liveness: notify on a DIFFERENT conn, must arrive here."""
        probe = None
        try:
            self._probe_event.clear()
            probe = await asyncpg.connect(self.dsn, timeout=self.connect_timeout)
            await probe.execute("select pg_notify($1, 'probe')", self.channel)
            await asyncio.wait_for(self._probe_event.wait(), self.probe_timeout)
            return True
        except (TimeoutError, OSError, asyncpg.Error):
            return False
        finally:
            if probe is not None:
                await probe.close()

    async def maintain(self) -> None:
        """Sweep-time liveness: probe when up, reconnect+self-test when down."""
        if self.alive and await self.probe():
            return
        if self.conn is not None and not self.conn.is_closed():
            await self.conn.close()
        self.conn = None
        await self.start()

    async def stop(self) -> None:
        if self.conn is not None and not self.conn.is_closed():
            try:
                await self.conn.remove_listener(self.channel, self._on_notify)
                await self.conn.close()
            except (OSError, asyncpg.Error):
                pass
        self.conn = None
