"""In-memory node step records for testability / future turn traces.

Recording is opt-in via ``node_trace_recording()``. Production turns leave the
buffer unset so there is no per-request allocation until we wire persistence.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any

_steps: ContextVar[list[NodeStepRecord] | None] = ContextVar("node_trace_steps", default=None)


@dataclass
class NodeStepRecord:
    """One graph node invocation: compact I/O for replay / tests."""

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


@contextmanager
def node_trace_recording() -> Iterator[list[NodeStepRecord]]:
    """Collect ``NodeStepRecord``s for the duration of the block."""
    buf: list[NodeStepRecord] = []
    token = _steps.set(buf)
    try:
        yield buf
    finally:
        _steps.reset(token)


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
