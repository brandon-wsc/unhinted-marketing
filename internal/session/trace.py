"""Node step records for testability + production turn traces (admin Trace viewer).

Recording is opt-in via ``node_trace_recording()`` (tests) or ``turn_trace(...)``
(production graph turns). Production flush is background + toggleable via
``NODE_TRACE_ENABLED``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any

from internal.config import settings
from internal.memory.database import SessionLocal
from internal.memory.models import SessionNodeStep

logger = logging.getLogger(__name__)

# Cap string leaves inside step output JSON (same spirit as LLM recorder).
MAX_OUTPUT_STRING_CHARS = 20_000

_steps: ContextVar[list[NodeStepRecord] | None] = ContextVar("node_trace_steps", default=None)
_turn_id: ContextVar[uuid.UUID | None] = ContextVar("node_trace_turn_id", default=None)
_turn_meta: ContextVar[dict[str, uuid.UUID | None] | None] = ContextVar(
    "node_trace_turn_meta", default=None
)
_pending: set[asyncio.Task] = set()


@dataclass
class NodeStepRecord:
    """One graph node invocation: compact I/O for replay / tests / admin."""

    node: str
    source_signal_ids_in: list[str] = field(default_factory=list)
    source_signal_ids_out: list[str] = field(default_factory=list)
    output_keys: list[str] = field(default_factory=list)
    output: dict[str, Any] = field(default_factory=dict)
    mode_in: str | None = None
    mode_out: str | None = None
    intent_out: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def current_turn_id() -> uuid.UUID | None:
    return _turn_id.get()


@contextmanager
def node_trace_recording() -> Iterator[list[NodeStepRecord]]:
    """Collect ``NodeStepRecord``s for the duration of the block (tests)."""
    buf: list[NodeStepRecord] = []
    token = _steps.set(buf)
    try:
        yield buf
    finally:
        _steps.reset(token)


@contextmanager
def turn_trace(
    *,
    turn_id: uuid.UUID | None = None,
    session_id: Any = None,
    user_id: Any = None,
    company_id: Any = None,
) -> Iterator[uuid.UUID]:
    """Bind a turn_id + collect steps; flush to DB on exit when enabled."""
    tid = turn_id or uuid.uuid4()
    buf: list[NodeStepRecord] = []
    steps_token = _steps.set(buf)
    turn_token = _turn_id.set(tid)
    meta_token = _turn_meta.set(
        {
            "session_id": _as_uuid(session_id),
            "user_id": _as_uuid(user_id),
            "company_id": _as_uuid(company_id),
        }
    )
    try:
        yield tid
    finally:
        _turn_meta.reset(meta_token)
        _turn_id.reset(turn_token)
        _steps.reset(steps_token)
        submit_steps(
            turn_id=tid,
            session_id=_as_uuid(session_id),
            user_id=_as_uuid(user_id),
            company_id=_as_uuid(company_id),
            steps=list(buf),
        )


def clear_node_trace() -> None:
    buf = _steps.get()
    if buf is not None:
        buf.clear()


def get_node_trace() -> list[NodeStepRecord]:
    return list(_steps.get() or [])


def record_node_step(
    node: str,
    state_in: dict[str, Any],
    output: dict[str, Any],
) -> NodeStepRecord | None:
    """Append a step when recording is active; otherwise no-op."""
    buf = _steps.get()
    if buf is None:
        return None
    sig_in = list(state_in.get("source_signal_ids") or [])
    if "source_signal_ids" in output:
        sig_out = list(output.get("source_signal_ids") or [])
    else:
        sig_out = sig_in
    rec = NodeStepRecord(
        node=node,
        source_signal_ids_in=sig_in,
        source_signal_ids_out=sig_out,
        output_keys=sorted(output.keys()),
        output=dict(output),
        mode_in=state_in.get("mode"),
        mode_out=output.get("mode", state_in.get("mode")),
        intent_out=output.get("intent"),
    )
    buf.append(rec)
    return rec


def submit_steps(
    *,
    turn_id: uuid.UUID,
    session_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    company_id: uuid.UUID | None,
    steps: list[NodeStepRecord],
) -> None:
    if not settings.node_trace_enabled or not steps:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("node steps dropped (no running event loop): turn=%s", turn_id)
        return
    task = loop.create_task(
        _persist_steps_safely(
            turn_id=turn_id,
            session_id=session_id,
            user_id=user_id,
            company_id=company_id,
            steps=steps,
        )
    )
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def _persist_steps_safely(
    *,
    turn_id: uuid.UUID,
    session_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    company_id: uuid.UUID | None,
    steps: list[NodeStepRecord],
) -> None:
    try:
        rows = [
            SessionNodeStep(
                session_id=session_id,
                user_id=user_id,
                company_id=company_id,
                turn_id=turn_id,
                seq=idx,
                node=step.node,
                mode_in=step.mode_in,
                mode_out=step.mode_out,
                intent_out=step.intent_out,
                source_signal_ids_in=list(step.source_signal_ids_in),
                source_signal_ids_out=list(step.source_signal_ids_out),
                output_keys=list(step.output_keys),
                output=_cap_output(step.output),
            )
            for idx, step in enumerate(steps)
        ]
        async with SessionLocal() as db:
            db.add_all(rows)
            await db.commit()
    except Exception:
        logger.warning("failed to persist node steps (turn=%s)", turn_id, exc_info=True)


async def drain(timeout: float = 10.0) -> None:
    if not _pending:
        return
    _done, pending = await asyncio.wait(_pending, timeout=timeout)
    if pending:
        logger.warning("node step drain timed out with %d pending writes", len(pending))


def _as_uuid(raw: Any) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError):
        return None


def _cap_output(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "<max_depth>"
    if isinstance(value, str):
        if value.startswith("data:") and ";base64," in value:
            mime = value.split(";", 1)[0]
            return f"{mime};base64,<{len(value)} chars>"
        if len(value) > MAX_OUTPUT_STRING_CHARS:
            return value[:MAX_OUTPUT_STRING_CHARS] + f"…[truncated {len(value) - MAX_OUTPUT_STRING_CHARS} chars]"
        return value
    if isinstance(value, dict):
        return {str(k): _cap_output(v, depth=depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > 100:
            return [_cap_output(v, depth=depth + 1) for v in value[:100]] + [
                f"…[+{len(value) - 100} items]"
            ]
        return [_cap_output(v, depth=depth + 1) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:MAX_OUTPUT_STRING_CHARS]
