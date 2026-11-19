"""Session chat inner loop — LangChain chat models (ADR 0060).

A hand-rolled ``bind_tools`` + ``astream`` loop (no ``create_agent`` /
ToolNode per the ADR). Provider mapping lives in ``router._lc_harness_model``
and mirrors the retired ``live_harness_model``: openai/openai_compatible →
``ChatOpenAI``, anthropic + claude-by-name → ``ChatAnthropic``,
gemini/vertex_ai → ``ChatGoogleGenerativeAI`` (Vertex Express api_key mode).
Tools are built per call and discarded — never stored on graph state or
FastAPI. Chat tools are read-only; publish-class names are never registered.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.utils import message_chunk_to_message
from langchain_core.tools import BaseTool, InjectedToolArg, tool
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from internal.llm.recorder import LlmCallRecordBuilder, mark_last_call, track
from internal.llm.resolve import resolve_llm_model
from internal.llm.router import (
    LlmProviderError,
    ModelTier,
    _aclose_stream,
    _estimate_lc_usage,
    _lc_harness_model,
    _wrap_lc_error,
)
from internal.memory import document_retrieve
from internal.memory.repos import list_top_signals
from internal.session import prompts
from internal.session.context import get_db
from internal.session.events import session_event_bus
from internal.session.io import omit_nulls
from internal.session.tiers import NODE_MODEL_TIERS
from schemas.tools import (
    QueryMarketTrendsResponse,
    QueryMarketTrendsSignal,
    ReadAttachmentResponse,
    ReadAttachmentSlice,
)

logger = logging.getLogger(__name__)

PUBLISH_TOOL_NAMES = frozenset({"publish_social_post"})
CHAT_TOOL_NAMES = frozenset({"query_market_trends", "read_attachment"})

# ADR 0047 §6 — per-turn read_attachment budget (chosen cap in the 2–3 range).
MAX_ATTACHMENT_READS_PER_TURN = 3

# Safety bound on the hand-rolled tool loop — far past any legit turn (the
# 3-read attachment budget ends read loops on its own).
_MAX_TOOL_ROUNDS = 32

# Match nodes._DELTA_FLUSH_CHARS — long replies must not overflow SSE queues.
_DELTA_FLUSH_CHARS = 24

_model_override: BaseChatModel | None = None


@dataclass
class ChatDeps:
    company_id: uuid.UUID | None = None
    # ADR 0047 §14 — owner scope is re-checked on every read_attachment call;
    # the ids the LLM emits are untrusted, so the tool needs both ids.
    user_id: uuid.UUID | None = None
    # Per-turn read_attachment counter (deps are rebuilt each turn).
    attachment_reads: int = 0


def set_chat_model_override(model: BaseChatModel | None) -> None:
    """Test hook: inject a scripted chat model. Pass None to restore live."""
    global _model_override
    _model_override = model


def _live_lc_model(tier: ModelTier) -> tuple[Any, str]:
    """``(ChatModel, label)`` for the tier — BYOK resolver mapping to a
    provider's LangChain chat model; raises ``LlmProviderError`` on
    unsupported/missing packages."""
    return _lc_harness_model(resolve_llm_model(tier))


def _live_lc_chat_model() -> tuple[Any, str]:
    return _live_lc_model(NODE_MODEL_TIERS["chat"] or ModelTier.CHEAP)


async def lookup_market_trends(
    region: str = "HK",
    limit: int = 20,
) -> QueryMarketTrendsResponse:
    """Read-only HK signal lookup from PostgreSQL (no second store)."""
    try:
        db = get_db()
    except RuntimeError:
        return QueryMarketTrendsResponse(region=region, notes="no session db")
    capped = max(1, min(int(limit), 50))
    rows = await list_top_signals(db, limit=capped, region=region)
    signals = [
        QueryMarketTrendsSignal(
            signal_id=row.signal_id,
            source=row.source,
            title=row.title,
            url=row.url,
            excerpt=row.excerpt,
            region=row.region,
            metrics=row.metrics or {},
        )
        for row in rows
    ]
    return QueryMarketTrendsResponse(
        region=region,
        signals=signals,
        ranked_signal_ids=[s.signal_id for s in signals],
    )


async def read_document(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    attachment_id: uuid.UUID,
    query: str | None = None,
    section: str | None = None,
) -> dict | None:
    """Module-level retrieve seam for ``read_attachment`` (ADR 0047 §6).

    Same monkeypatchable style as ``document_ingest.embed_texts``: unpatched it
    delegates to ``document_retrieve.read_document`` looked up on the module, so
    patching either site keeps tests hermetic.
    """
    return await document_retrieve.read_document(
        db,
        company_id=company_id,
        user_id=user_id,
        attachment_id=attachment_id,
        query=query,
        section=section,
    )


async def _run_query_market_trends(
    deps: ChatDeps,
    region: str = "HK",
    limit: int = 20,
) -> QueryMarketTrendsResponse:
    del deps  # company_id reserved; corpus is still HK-wide (same as trend_searcher)
    return await lookup_market_trends(region, limit)


async def _run_read_attachment(
    deps: ChatDeps,
    attachment_id: str,
    query: str | None = None,
    section: str | None = None,
) -> ReadAttachmentResponse:
    """Read-only slices from one session attachment (ADR 0047 §5/§6/§14).

    Never raises and never returns full document text: every refusal is
    ``slices=[]`` + a non-empty ``error``. A call with neither ``query`` nor
    ``section`` is refused before the seam (the service would refuse anyway);
    ``attachment_reads`` is the per-turn budget — only calls that pass local
    validation count against it.
    """
    q = (query or "").strip()
    s = (section or "").strip()
    if not q and not s:
        return ReadAttachmentResponse(error="missing_query_or_section: pass query= or section=")
    try:
        att_id = uuid.UUID(str(attachment_id))
    except (ValueError, TypeError, AttributeError):
        return ReadAttachmentResponse(error="invalid_attachment_id")
    if deps.company_id is None or deps.user_id is None:
        # §14 — without both ids the tool cannot re-check owner scope.
        return ReadAttachmentResponse(error="missing_scope")
    try:
        db = get_db()
    except RuntimeError:
        return ReadAttachmentResponse(error="no_session_db")
    deps.attachment_reads += 1
    if deps.attachment_reads > MAX_ATTACHMENT_READS_PER_TURN:
        return ReadAttachmentResponse(
            error=f"budget_exceeded: max {MAX_ATTACHMENT_READS_PER_TURN} reads per turn"
        )
    try:
        result = await read_document(
            db,
            company_id=deps.company_id,
            user_id=deps.user_id,
            attachment_id=att_id,
            query=q or None,
            section=s or None,
        )
    except Exception as exc:  # noqa: BLE001 — the tool must never raise to the LLM
        logger.warning("read_attachment seam failed: %s", exc)
        return ReadAttachmentResponse(error="read_failed")
    if not isinstance(result, dict) or not result:
        # §14 — unknown / out-of-scope ids are indistinguishable.
        return ReadAttachmentResponse(error="not_found_or_out_of_scope")
    slices = [
        ReadAttachmentSlice(
            chunk_id=str(item.get("chunk_id") or ""),
            ref=str(item.get("ref") or ""),
            text=str(item.get("text") or ""),
        )
        for item in (result.get("slices") or [])[:5]
        if isinstance(item, dict)
    ]
    return ReadAttachmentResponse(slices=slices, partial=bool(result.get("partial")))


@tool
async def query_market_trends(
    deps: Annotated[ChatDeps, InjectedToolArg],
    region: str = "HK",
    limit: int = 20,
) -> str:
    """Read-only lookup of recent Hong Kong market signals from PostgreSQL."""
    response = await _run_query_market_trends(deps, region, limit)
    return response.model_dump_json()


@tool
async def read_attachment(
    deps: Annotated[ChatDeps, InjectedToolArg],
    attachment_id: str,
    query: str | None = None,
    section: str | None = None,
) -> str:
    """Read-only slices from one session attachment (never full document text).

    Pass ``attachment_id`` plus a ``query`` or ``section``; refusals return
    ``slices=[]`` with a non-empty ``error`` (ADR 0047 §5/§6/§14).
    """
    response = await _run_read_attachment(deps, attachment_id, query, section)
    return response.model_dump_json()


@tool
async def slow_probe(deps: Annotated[ChatDeps, InjectedToolArg]) -> str:
    """Test-only: sleep so Stop/cancel can be observed mid-tool. Never register in prod."""
    del deps
    await asyncio.sleep(10)
    return "slept"


def chat_tools(extra_tools: Sequence[Any] = ()) -> list[Any]:
    """LangChain tools on the chat loop — publish-class names never registered."""
    tools: list[Any] = [query_market_trends, read_attachment]
    for extra in extra_tools:
        tools.append(extra if isinstance(extra, BaseTool) else tool(extra))
    return tools


async def _publish_deltas(
    session_id: uuid.UUID, pending: list[str], *, force: bool = False
) -> None:
    text = "".join(pending)
    if not text or (not force and len(text) < _DELTA_FLUSH_CHARS):
        return
    pending.clear()
    try:
        await session_event_bus.publish(session_id, "message.delta", {"content": text})
    except Exception:
        logger.exception("failed to publish message.delta")


def _model_label(model: Any) -> str:
    name = getattr(model, "model_name", None) or getattr(model, "model", None)
    return str(name) if name else type(model).__name__


def _stash_partial(rec: LlmCallRecordBuilder, parts: list[str]) -> None:
    rec.response_text = "".join(parts).strip() or None


def _merge_lc_usage(totals: dict[str, int], usage: Any) -> None:
    """Accumulate ``usage_metadata`` across tool-loop rounds into ``totals``."""
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
        if isinstance(value, int):
            totals[key] = totals.get(key, 0) + value
    details = (
        usage.get("input_token_details")
        if isinstance(usage, dict)
        else getattr(usage, "input_token_details", None)
    )
    cached = (
        details.get("cache_read")
        if isinstance(details, dict)
        else getattr(details, "cache_read", None)
    )
    if isinstance(cached, int):
        totals["cache_read_input_tokens"] = totals.get("cache_read_input_tokens", 0) + cached


async def _run_lc_tool_call(call: dict, tools: dict[str, Any], deps: ChatDeps) -> ToolMessage:
    """Dispatch one model tool_call; ``deps`` rides in as the injected arg."""
    name = str(call.get("name") or "")
    call_id = str(call.get("id") or name or "tool_call")
    tool_obj = tools.get(name)
    if tool_obj is None:
        return ToolMessage(
            content=f'{{"error": "unknown_tool:{name}"}}',
            tool_call_id=call_id,
        )
    args = dict(call.get("args") or {})
    args["deps"] = deps
    result = await tool_obj.ainvoke({**call, "args": args, "id": call_id})
    if isinstance(result, ToolMessage):
        return result
    return ToolMessage(content=str(result), tool_call_id=call_id)


async def _stream_round(
    bound: Any,
    chat: Any,
    messages: list[Any],
    *,
    rec: LlmCallRecordBuilder,
    usage: dict[str, int],
    parts: list[str],
    pending: list[str],
    session_id: uuid.UUID | None,
) -> Any:
    """Stream one model round; return the merged reply or ``None`` on zero chunks."""
    agen = bound.astream(messages)
    acc = None
    saw_usage = False
    round_text: list[str] = []
    try:
        async for chunk in agen:
            acc = chunk if acc is None else acc + chunk
            chunk_usage = getattr(chunk, "usage_metadata", None)
            if chunk_usage:
                saw_usage = True
                _merge_lc_usage(usage, chunk_usage)
                rec.set_usage(usage)
            piece = chunk.content if isinstance(chunk.content, str) else ""
            if piece:
                rec.mark_first_token()
                parts.append(piece)
                pending.append(piece)
                round_text.append(piece)
                if session_id:
                    await _publish_deltas(session_id, pending)
    except ValueError as exc:
        # BaseChatModel.astream raises when a round yields zero
        # chunks — treat as an empty reply, not a provider error.
        if "generation chunks" not in str(exc):
            raise
    finally:
        await _aclose_stream(agen)
        if acc is not None and not saw_usage:
            estimate = _estimate_lc_usage(
                chat,
                messages,
                completion_messages=[message_chunk_to_message(acc)],
                completion_text="".join(round_text),
            )
            if estimate is not None:
                _merge_lc_usage(usage, estimate)
                rec.set_usage(usage)
    return acc


async def _stream_chat_reply_lc(
    *,
    chat: BaseChatModel,
    model_label: str,
    user_prompt: str,
    session_id: uuid.UUID | None,
    deps: ChatDeps,
    extra_tools: Sequence[Any],
) -> str | None:
    """Hand-rolled ``bind_tools`` + ``astream`` loop (ADR 0060 — no ToolNode)."""
    tools = chat_tools(extra_tools)
    by_name = {t.name: t for t in tools}
    bound = chat.bind_tools(tools)
    messages: list[Any] = [
        SystemMessage(content=prompts.CHAT),
        HumanMessage(content=user_prompt),
    ]
    parts: list[str] = []
    pending: list[str] = []
    usage: dict[str, int] = {}
    output: str | None = None
    with track(
        kind="chat_text",
        tier=NODE_MODEL_TIERS["chat"],
        model=model_label,
        system=prompts.CHAT,
        user=user_prompt,
    ) as rec:
        try:
            for _ in range(_MAX_TOOL_ROUNDS):
                acc = await _stream_round(
                    bound,
                    chat,
                    messages,
                    rec=rec,
                    usage=usage,
                    parts=parts,
                    pending=pending,
                    session_id=session_id,
                )
                if acc is None:
                    break
                reply = message_chunk_to_message(acc)
                tool_calls = list(reply.tool_calls or [])
                invalid = list(getattr(reply, "invalid_tool_calls", None) or [])
                if not tool_calls and not invalid:
                    output = reply.content if isinstance(reply.content, str) else ""
                    break
                messages.append(reply)
                for call in tool_calls:
                    messages.append(await _run_lc_tool_call(call, by_name, deps))
                for call in invalid:
                    call_id = str(call.get("id") or call.get("name") or "tool_call")
                    messages.append(
                        ToolMessage(
                            content='{"error": "invalid_tool_call"}',
                            tool_call_id=call_id,
                        )
                    )
            else:
                logger.warning("chat tool loop hit %s rounds; returning partial", _MAX_TOOL_ROUNDS)
            if session_id:
                await _publish_deltas(session_id, pending, force=True)
        except asyncio.CancelledError:
            _stash_partial(rec, parts)
            raise
        except LlmProviderError:
            _stash_partial(rec, parts)
            raise
        except Exception as exc:
            _stash_partial(rec, parts)
            raise _wrap_lc_error(exc, model=model_label) from exc
        text = (output if output is not None else "".join(parts)).strip()
        rec.response_text = text or None
    return text or None


OutT = TypeVar("OutT", bound=BaseModel)


def _structured_from_text(out_type: type[OutT], content: Any) -> OutT | None:
    """Plain-text JSON fallback when a model answers instead of calling ``out_type``."""
    if isinstance(content, str):
        text = content
    else:
        text = "".join(
            str(block.get("text") or "") for block in content if isinstance(block, dict)
        )
    try:
        return out_type.model_validate(omit_nulls(json.loads(text)))
    except (ValueError, TypeError):
        return None


async def run_lc_tool_loop(
    *,
    chat: BaseChatModel,
    system: str,
    user_prompt: str,
    deps: Any,
    tools: Sequence[Any],
    out_type: type[OutT],
    rec: LlmCallRecordBuilder,
) -> OutT | None:
    """``bind_tools`` loop for typed-output harnesses (ADR 0060 — no ToolNode).

    ``out_type`` is bound alongside the real tools — the same mechanism
    Pydantic AI uses for ``output_type`` — so the model can interleave real
    tool calls and finish by "calling" the output schema. A no-tool-call
    reply falls back to parsing its text as JSON. Provider errors raise
    ``LlmProviderError``; everything else (tool bugs, validation misses)
    propagates for the caller's parse-fail path.
    """
    by_name = {t.name: t for t in tools}
    out_name = out_type.__name__
    bound = chat.bind_tools([*tools, out_type])
    messages: list[Any] = [
        SystemMessage(content=system),
        HumanMessage(content=user_prompt),
    ]
    usage: dict[str, int] = {}
    for _ in range(_MAX_TOOL_ROUNDS):
        try:
            reply = await bound.ainvoke(messages)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise _wrap_lc_error(exc, model=_model_label(chat)) from exc
        if getattr(reply, "usage_metadata", None):
            _merge_lc_usage(usage, reply.usage_metadata)
        else:
            estimate = _estimate_lc_usage(chat, messages, completion_messages=[reply])
            if estimate is not None:
                _merge_lc_usage(usage, estimate)
        if usage:
            rec.set_usage(usage)
        calls = list(getattr(reply, "tool_calls", None) or [])
        invalid = list(getattr(reply, "invalid_tool_calls", None) or [])
        out_calls = [c for c in calls if str(c.get("name") or "") == out_name]
        real_calls = [c for c in calls if str(c.get("name") or "") != out_name]
        if real_calls or invalid:
            messages.append(reply)
            for call in real_calls:
                messages.append(await _run_lc_tool_call(call, by_name, deps))
            for call in invalid:
                call_id = str(call.get("id") or call.get("name") or "tool_call")
                messages.append(
                    ToolMessage(content='{"error": "invalid_tool_call"}', tool_call_id=call_id)
                )
        if out_calls:
            return out_type.model_validate(omit_nulls(dict(out_calls[-1].get("args") or {})))
        if not calls and not invalid:
            return _structured_from_text(out_type, getattr(reply, "content", ""))
    logger.warning("lc tool loop hit %s rounds; parse miss", _MAX_TOOL_ROUNDS)
    return None


async def run_typed_lc_agent(
    *,
    chat: BaseChatModel,
    model_label: str,
    tier: ModelTier | None,
    system: str,
    user_prompt: str,
    deps: Any,
    tools: Sequence[Any],
    out_type: type[OutT],
    is_valid: Callable[[OutT], bool],
    log_tag: str,
) -> OutT | None:
    """Recorder + error contract shared by the research/execute LC paths.

    Same contract as the Pydantic AI runners: provider errors raise
    ``LlmProviderError``, cancels propagate, every other failure is a
    parse miss → ``None``.
    """
    with track(
        kind="chat_json",
        tier=tier,
        model=model_label,
        system=system,
        user=user_prompt,
    ) as rec:
        try:
            parsed = await run_lc_tool_loop(
                chat=chat,
                system=system,
                user_prompt=user_prompt,
                deps=deps,
                tools=tools,
                out_type=out_type,
                rec=rec,
            )
            if parsed is not None:
                rec.response_text = parsed.model_dump_json()
        except asyncio.CancelledError:
            raise
        except LlmProviderError:
            raise
        except Exception:
            mark_last_call(parse_ok=False, fallback_used=True)
            logger.exception("%s agent failed", log_tag)
            return None
        if parsed is None or not is_valid(parsed):
            mark_last_call(parse_ok=False, fallback_used=True)
            return None
        mark_last_call(parse_ok=True)
        return parsed


async def stream_chat_reply(
    *,
    user_prompt: str,
    session_id: uuid.UUID | None,
    deps: ChatDeps,
    extra_tools: Sequence[Any] = (),
) -> str | None:
    """Run the chat agent, fan out message.delta, return the final text."""
    if _model_override is not None:
        chat, label = _model_override, _model_label(_model_override)
    else:
        chat, label = _live_lc_chat_model()
    return await _stream_chat_reply_lc(
        chat=chat,
        model_label=label,
        user_prompt=user_prompt,
        session_id=session_id,
        deps=deps,
        extra_tools=extra_tools,
    )
