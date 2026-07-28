"""In-process SSE fan-out for session events (single-worker MVP)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

# Keepalive so proxies don't idle-close the stream.
HEARTBEAT_SECONDS = 15.0
QUEUE_MAXSIZE = 64


class SessionEventBus:
    def __init__(self) -> None:
        self._subs: dict[uuid.UUID, set[asyncio.Queue[dict[str, Any] | None]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(self, session_id: uuid.UUID, event_type: str, data: dict[str, Any] | None = None) -> None:
        payload = {"type": event_type, "data": data or {}}
        async with self._lock:
            queues = list(self._subs.get(session_id, ()))
        for q in queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("SSE queue full for session %s — dropping %s", session_id, event_type)

    async def publish_many(self, session_id: uuid.UUID, events: list[dict[str, Any]]) -> None:
        for ev in events:
            etype = str(ev.get("type") or "event")
            data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
            await self.publish(session_id, etype, data)

    async def subscribe(self, session_id: uuid.UUID) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        async with self._lock:
            self._subs[session_id].add(queue)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield {"type": "heartbeat", "data": {}}
                    continue
                if item is None:
                    break
                yield item
        finally:
            async with self._lock:
                subs = self._subs.get(session_id)
                if subs is not None:
                    subs.discard(queue)
                    if not subs:
                        self._subs.pop(session_id, None)


def format_sse(event_type: str, data: dict[str, Any]) -> str:
    body = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {body}\n\n"


session_event_bus = SessionEventBus()
