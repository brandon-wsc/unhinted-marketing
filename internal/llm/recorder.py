"""Persist every LLM call for prompt/node debugging (ADR 0005).

The router wraps each provider call in ``track(...)``; the graph (or a worker)
wraps the calling unit in ``call_context(...)`` so records carry correlation
(session/user/company + node). Records buffer in the active context and flush
as background DB writes when it exits — recording never blocks or breaks a
turn. Callers mark the last call with ``mark_last_call(parse_ok=…,
fallback_used=…)`` after validating output, which is the "which step went
wrong" signal.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from internal.config import settings
from internal.memory.database import SessionLocal
from internal.memory.models import LlmCallRecord

logger = logging.getLogger(__name__)

# Stored prompts/responses are capped so a runaway payload can't bloat the row.
MAX_STORED_CHARS = 50_000

_context: ContextVar[CallContext | None] = ContextVar("llm_call_context", default=None)
_pending: set[asyncio.Task] = set()


def _cap(text: str | None) -> str | None:
    if text is None or len(text) <= MAX_STORED_CHARS:
        return text
    return text[:MAX_STORED_CHARS] + f"…[truncated {len(text) - MAX_STORED_CHARS} chars]"


def _uuid_or_none(raw: Any) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError):
        return None


def _usage_int(usage: Any, key: str) -> int | None:
    value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass
class LlmCallRecordBuilder:
    """Row under construction; the router fills it while the call runs."""

    kind: str
    caller: str = ""
    node: str | None = None
    session_id: uuid.UUID | None = None
    turn_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    tier: str | None = None
    model: str | None = None
    temperature: float | None = None
    system_prompt: str | None = None
    user_prompt: str | None = None
    response_text: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    status: str = "ok"
    error: dict | None = None
    parse_ok: bool | None = None
    fallback_used: bool = False
    key_source: str | None = None
    key_last4: str | None = None
    ttft_ms: int | None = None
    cached_tokens: int | None = None
    _started_mono: float = field(default_factory=time.monotonic)

    def fail(self, status: str, error: dict) -> None:
        """Pre-mark a specific failure; ``track``'s generic except keeps it."""
        self.status = status
        self.error = error

    def mark_first_token(self) -> None:
        """Stamp time-to-first-token once; later calls are no-ops."""
        if self.ttft_ms is None:
            self.ttft_ms = int((time.monotonic() - self._started_mono) * 1000)

    def set_usage(self, usage: Any) -> None:
        """Accept LiteLLM or Pydantic AI usage (object or dict)."""
        if usage is None:
            return
        prompt = _usage_int(usage, "prompt_tokens")
        if prompt is None:
            prompt = _usage_int(usage, "input_tokens")
        if prompt is None:
            prompt = _usage_int(usage, "prompt_token_count")
        completion = _usage_int(usage, "completion_tokens")
        if completion is None:
            completion = _usage_int(usage, "output_tokens")
        if completion is None:
            completion = _usage_int(usage, "candidates_token_count")
        total = _usage_int(usage, "total_tokens")
        if total is None:
            total = _usage_int(usage, "total_token_count")
        # Prompt-cache hits — provider shapes differ; first non-None wins.
        # LiteLLM/DeepSeek: prompt_cache_hit_tokens; OpenAI:
        # prompt_tokens_details.cached_tokens; Anthropic:
        # cache_read_input_tokens; pydantic-ai: cache_read_tokens.
        cached = _usage_int(usage, "prompt_cache_hit_tokens")
        if cached is None:
            details = (
                usage.get("prompt_tokens_details")
                if isinstance(usage, dict)
                else getattr(usage, "prompt_tokens_details", None)
            )
            if details is not None:
                cached = _usage_int(details, "cached_tokens")
        if cached is None:
            cached = _usage_int(usage, "cache_read_input_tokens")
        if cached is None:
            cached = _usage_int(usage, "cache_read_tokens")
        if prompt is not None:
            self.prompt_tokens = prompt
        if completion is not None:
            self.completion_tokens = completion
        if cached is not None:
            self.cached_tokens = cached
        self.total_tokens = (
            total if total is not None else (prompt or 0) + (completion or 0) or None
        )

    def to_model(self) -> LlmCallRecord:
        response = self.response_text
        if self.kind == "image" and response and response.startswith("data:"):
            mime = response.split(";", 1)[0]
            response = f"{mime};base64,<{len(self.response_text)} chars>"
        return LlmCallRecord(
            caller=self.caller or "unknown",
            node=self.node,
            session_id=self.session_id,
            turn_id=self.turn_id,
            user_id=self.user_id,
            company_id=self.company_id,
            kind=self.kind,
            tier=self.tier,
            model=self.model,
            temperature=self.temperature,
            system_prompt=_cap(self.system_prompt),
            user_prompt=_cap(self.user_prompt),
            response_text=_cap(response),
            latency_ms=self.latency_ms,
            ttft_ms=self.ttft_ms,
            cached_tokens=self.cached_tokens,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
            status=self.status,
            error=self.error,
            parse_ok=self.parse_ok,
            fallback_used=self.fallback_used,
            key_source=self.key_source,
            key_last4=self.key_last4,
        )


@dataclass
class CallContext:
    """Correlation for every LLM call made inside one node / worker unit."""

    caller: str
    node: str | None = None
    session_id: uuid.UUID | None = None
    turn_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    records: list[LlmCallRecordBuilder] = field(default_factory=list)


@contextmanager
def call_context(
    *,
    caller: str,
    node: str | None = None,
    session_id: Any = None,
    turn_id: Any = None,
    user_id: Any = None,
    company_id: Any = None,
) -> Iterator[CallContext]:
    """Scope correlation for contained ``track`` calls; flush records on exit."""
    # Prefer explicit turn_id; else inherit from session turn_trace ContextVar.
    from internal.session.trace import current_turn_id

    resolved_turn = _uuid_or_none(turn_id) or current_turn_id()
    ctx = CallContext(
        caller=caller,
        node=node,
        session_id=_uuid_or_none(session_id),
        turn_id=resolved_turn,
        user_id=_uuid_or_none(user_id),
        company_id=_uuid_or_none(company_id),
    )
    token = _context.set(ctx)
    try:
        yield ctx
    finally:
        _context.reset(token)
        for rec in ctx.records:
            submit(rec)


def mark_last_call(
    *, parse_ok: bool | None = None, fallback_used: bool | None = None
) -> None:
    """Mark the most recent tracked call (post-validation); no-op without context."""
    ctx = _context.get()
    if ctx is None or not ctx.records:
        return
    rec = ctx.records[-1]
    if parse_ok is not None:
        rec.parse_ok = parse_ok
    if fallback_used is not None:
        rec.fallback_used = fallback_used


def _stamp_key_meta(rec: LlmCallRecordBuilder) -> None:
    """Copy resolver source/last4 onto the record. Recording must never raise."""
    try:
        from internal.llm.resolve import resolve_image, resolve_llm_model

        resolved = None
        if rec.kind == "image":
            resolved = resolve_image()
        elif rec.tier:
            resolved = resolve_llm_model(rec.tier)
        if resolved is None:
            return
        rec.key_source = resolved.source
        rec.key_last4 = resolved.key_last4
    except Exception:
        logger.debug("could not stamp key_source on LLM record", exc_info=True)


@contextmanager
def track(
    *,
    kind: str,
    tier: Any = None,
    model: str | None = None,
    temperature: float | None = None,
    system: str | None = None,
    user: str | None = None,
) -> Iterator[LlmCallRecordBuilder]:
    """Time + classify one provider call; buffer/submit the record on exit."""
    # Lazy import: router imports recorder, so recorder cannot import router at top.
    from internal.llm.router import LlmProviderError

    rec = LlmCallRecordBuilder(
        kind=kind,
        tier=getattr(tier, "value", tier),
        model=model,
        temperature=temperature,
        system_prompt=system,
        user_prompt=user,
    )
    ctx = _context.get()
    if ctx is not None:
        rec.caller = ctx.caller
        rec.node = ctx.node
        rec.session_id = ctx.session_id
        rec.turn_id = ctx.turn_id
        rec.user_id = ctx.user_id
        rec.company_id = ctx.company_id

    _stamp_key_meta(rec)

    start = time.monotonic()
    rec._started_mono = start
    try:
        yield rec
    except (asyncio.CancelledError, GeneratorExit):
        if rec.status == "ok":
            rec.status = "cancelled"
        raise
    except LlmProviderError as exc:
        if rec.status == "ok":
            rec.status = "provider_error"
            rec.error = exc.to_event_data()
        raise
    except Exception as exc:
        if rec.status == "ok":
            rec.status = "error"
            rec.error = {"kind": "internal", "message": str(exc)[:500]}
        raise
    finally:
        rec.latency_ms = int((time.monotonic() - start) * 1000)
        if ctx is not None:
            ctx.records.append(rec)
        else:
            submit(rec)


def submit(rec: LlmCallRecordBuilder) -> None:
    """Fire-and-forget persist; recording failure must never break a turn."""
    if not settings.llm_record_enabled:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("LLM record dropped (no running event loop): %s", rec.caller)
        return
    task = loop.create_task(_persist_safely(rec))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def _persist_safely(rec: LlmCallRecordBuilder) -> None:
    try:
        async with SessionLocal() as db:
            db.add(rec.to_model())
            await db.commit()
    except Exception:
        logger.warning("failed to persist LLM call record (%s)", rec.caller, exc_info=True)


async def drain(timeout: float = 10.0) -> None:
    """Await pending writes — CLI/scheduler call this before process exit."""
    if not _pending:
        return
    _done, pending = await asyncio.wait(_pending, timeout=timeout)
    if pending:
        logger.warning("LLM record drain timed out with %d pending writes", len(pending))
