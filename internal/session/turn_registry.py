"""In-process registry for in-flight session turns (ADR 0004).

Single-process only — same class of limit as the in-memory SSE bus.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnEntry:
    task: asyncio.Task[Any]
    pre_state: dict[str, Any]
    user_message_id: uuid.UUID
    message_ids: list[uuid.UUID] = field(default_factory=list)
    cancelling: bool = False
    discarded: asyncio.Event = field(default_factory=asyncio.Event)


class SessionTurnRegistry:
    def __init__(self) -> None:
        self._entries: dict[uuid.UUID, TurnEntry] = {}
        self._lock = asyncio.Lock()

    def get(self, session_id: uuid.UUID) -> TurnEntry | None:
        return self._entries.get(session_id)

    def is_busy(self, session_id: uuid.UUID) -> bool:
        entry = self._entries.get(session_id)
        return entry is not None and not entry.task.done()

    async def begin(
        self,
        session_id: uuid.UUID,
        *,
        task: asyncio.Task[Any],
        pre_state: dict[str, Any],
        user_message_id: uuid.UUID,
    ) -> TurnEntry:
        async with self._lock:
            existing = self._entries.get(session_id)
            if existing is not None and not existing.task.done():
                raise RuntimeError("session turn already in flight")
            entry = TurnEntry(
                task=task,
                pre_state=copy.deepcopy(pre_state),
                user_message_id=user_message_id,
                message_ids=[user_message_id],
            )
            self._entries[session_id] = entry
            return entry

    def track_message(self, session_id: uuid.UUID, message_id: uuid.UUID) -> None:
        entry = self._entries.get(session_id)
        if entry is not None and message_id not in entry.message_ids:
            entry.message_ids.append(message_id)

    async def clear(self, session_id: uuid.UUID, *, entry: TurnEntry | None = None) -> None:
        async with self._lock:
            current = self._entries.get(session_id)
            if current is None:
                return
            if entry is not None and current is not entry:
                return
            del self._entries[session_id]


session_turn_registry = SessionTurnRegistry()
