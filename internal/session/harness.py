"""Session chat inner loop — ``langchain.agents.create_agent`` (ADR 0061).

The chat + typed-output inner loops run on ``create_agent`` — a leaf
CompiledStateGraph that is never given a checkpointer or store (ADR 0061
supersedes ADR 0060's no-nested-graph clause; ``SessionState`` ownership is
unchanged). Typed outputs ride ``ToolStrategy`` — the model finishes by
"calling" the output schema in the same model call. Provider mapping lives
in ``router.lc_harness_model``: openai/openai_compatible → ``ChatOpenAI``,
anthropic + claude-by-name → ``ChatAnthropic``, gemini/vertex_ai →
``ChatGoogleGenerativeAI`` (Vertex Express api_key mode). Tools are built
per call and close over ``deps`` — never stored on graph state or FastAPI.
Chat tools are read-only; publish-class names are never registered.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from langchain.agents import create_agent
from langchain.agents.structured_output import StructuredOutputError, ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
)
from langchain_core.messages.utils import message_chunk_to_message
from langchain_core.tools import BaseTool, tool
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from internal.llm.recorder import LlmCallRecordBuilder, mark_last_call, track
from internal.llm.resolve import resolve_llm_model
from internal.llm.router import (
    LlmProviderError,
    ModelTier,
    aclose_stream,
    estimate_lc_usage,
    lc_harness_model,
    map_lc_error,
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

# Safety bound on the agent loop — far past any legit turn (the 3-read
# attachment budget ends read loops on its own). LangGraph counts supersteps
# (model node + tool node ≈ 2 per round), not model calls.
_MAX_TOOL_ROUNDS = 32
_RECURSION_LIMIT = 2 * _MAX_TOOL_ROUNDS + 2

# message.delta publish threshold — long replies must not overflow SSE queues.
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


def live_lc_model(tier: ModelTier) -> tuple[Any, str]:
    """``(ChatModel, label)`` for the tier — BYOK resolver mapping to a
    provider's LangChain chat model; raises ``LlmProviderError`` on
    unsupported/missing packages."""
    return lc_harness_model(resolve_llm_model(tier))


def live_lc_chat_model() -> tuple[Any, str]:
    return live_lc_model(NODE_MODEL_TIERS["chat"] or ModelTier.CHEAP)


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
async def query_market_trends(region: str = "HK", limit: int = 20) -> str:
    """Read-only lookup of recent Hong Kong market signals from PostgreSQL."""
    response = await lookup_market_trends(region, limit)
    return response.model_dump_json()


def read_attachment_tool(deps: ChatDeps) -> BaseTool:
    """Build the ``read_attachment`` tool bound to this call's ``deps``."""

    @tool
    async def read_attachment(
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

    return read_attachment


def with_extra_tools(base: list[Any], extra_tools: Sequence[Any]) -> list[Any]:
    """Append ``extra_tools`` — ``BaseTool`` instances pass through, callables wrap via ``tool``."""
    for extra in extra_tools:
        base.append(extra if isinstance(extra, BaseTool) else tool(extra))
    return base


def chat_tools(deps: ChatDeps, extra_tools: Sequence[Any] = ()) -> list[Any]:
    """LangChain tools on the chat loop — publish-class names never registered."""
    return with_extra_tools([query_market_trends, read_attachment_tool(deps)], extra_tools)


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


def model_label(model: Any) -> str:
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


def _estimate_if_no_usage(
    chat: Any,
    usage: dict[str, int],
    *,
    messages: Sequence[Any] = (),
    completion_messages: Sequence[Any] = (),
) -> None:
    """One client-side estimate when the provider reported no usage at all.

    Providers that ignore ``include_usage`` would otherwise record NULL token
    counts; the final agent state's message list approximates every round's
    prompt + completion in one estimate.
    """
    if usage:
        return
    estimate = estimate_lc_usage(chat, messages, completion_messages=completion_messages)
    if estimate is not None:
        _merge_lc_usage(usage, estimate)


def _last_ai(messages: Sequence[Any]) -> AIMessage | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


async def _consume_agent_stream(
    agen: Any,
    *,
    rec: LlmCallRecordBuilder,
    usage: dict[str, int],
    parts: list[str],
    pending: list[str],
    session_id: uuid.UUID | None,
    final_messages: list[Any],
    acc_box: list[AIMessageChunk | None],
) -> None:
    """Consume the agent stream into ``final_messages`` / ``acc_box``.

    ``messages`` payloads are ``(chunk, metadata)`` — only model-node
    ``AIMessageChunk`` deltas fan out to ``message.delta``; ``values``
    payloads carry the post-node state snapshot (full message list). Each
    ``values`` event ends a superstep, so the model chunks that follow it
    are a new round — ``acc`` holds only the current round's partial.
    Both out-params update live so an aborted stream still yields the
    committed messages plus the in-flight partial.
    """
    acc: AIMessageChunk | None = None
    async for mode, payload in agen:
        if mode == "values":
            final_messages[:] = list(payload.get("messages") or [])
            acc = None
            acc_box[0] = None
            continue
        chunk, meta = payload
        if not isinstance(chunk, AIMessageChunk) or meta.get("langgraph_node") != "model":
            continue
        acc = chunk if acc is None else acc + chunk
        acc_box[0] = acc
        chunk_usage = getattr(chunk, "usage_metadata", None)
        if chunk_usage:
            _merge_lc_usage(usage, chunk_usage)
            rec.set_usage(usage)
        piece = chunk.content if isinstance(chunk.content, str) else ""
        if piece:
            rec.mark_first_token()
            parts.append(piece)
            pending.append(piece)
            if session_id:
                await _publish_deltas(session_id, pending)


def _estimate_prompt_and_completions(
    system: str,
    user_prompt: str,
    final_messages: Sequence[Any],
    acc: AIMessageChunk | None,
    *,
    aborted: bool = False,
) -> tuple[Sequence[Any], Sequence[Any]]:
    """Prompt/completion split for the usage estimate.

    ``create_agent`` keeps ``system_prompt`` out of ``state.messages`` —
    prepend it back so the estimate counts the real model input. On an
    aborted stream (cancel / recursion cap) the last state snapshot is
    everything the in-flight round was sent; the merged partial ``acc``
    is its reply (ADR 0061 §2 — sent messages + merged partial).
    """
    if aborted:
        return (
            [SystemMessage(content=system), *final_messages],
            [message_chunk_to_message(acc)] if acc is not None else [],
        )
    last_ai = _last_ai(final_messages)
    if last_ai is not None:
        return (
            [SystemMessage(content=system), *[m for m in final_messages if m is not last_ai]],
            [last_ai],
        )
    return (
        [SystemMessage(content=system), HumanMessage(content=user_prompt)],
        [message_chunk_to_message(acc)] if acc is not None else [],
    )


async def _stream_chat_reply_lc(
    *,
    chat: BaseChatModel,
    label: str,
    user_prompt: str,
    session_id: uuid.UUID | None,
    deps: ChatDeps,
    extra_tools: Sequence[Any],
) -> str | None:
    """``create_agent`` chat loop streamed via ``stream_mode="messages"``."""
    agent = create_agent(
        chat,
        tools=chat_tools(deps, extra_tools),
        system_prompt=prompts.CHAT,
    )
    parts: list[str] = []
    pending: list[str] = []
    usage: dict[str, int] = {}
    final_messages: list[Any] = []
    acc_box: list[AIMessageChunk | None] = [None]
    stream_done = False
    with track(
        kind="chat_text",
        tier=NODE_MODEL_TIERS["chat"],
        model=label,
        system=prompts.CHAT,
        user=user_prompt,
    ) as rec:
        agen = agent.astream(
            {"messages": [HumanMessage(content=user_prompt)]},
            stream_mode=["messages", "values"],
            config={"recursion_limit": _RECURSION_LIMIT},
        )
        try:
            await _consume_agent_stream(
                agen,
                rec=rec,
                usage=usage,
                parts=parts,
                pending=pending,
                session_id=session_id,
                final_messages=final_messages,
                acc_box=acc_box,
            )
            stream_done = True
        except ValueError as exc:
            # BaseChatModel.astream raises when a round yields zero
            # chunks — treat as an empty reply, not a provider error.
            if "generation chunks" not in str(exc):
                _stash_partial(rec, parts)
                raise map_lc_error(exc, model=label) from exc
        except asyncio.CancelledError:
            _stash_partial(rec, parts)
            raise
        except GraphRecursionError:
            logger.warning("chat agent hit %s supersteps; returning partial", _RECURSION_LIMIT)
        except LlmProviderError:
            _stash_partial(rec, parts)
            raise
        except Exception as exc:
            _stash_partial(rec, parts)
            raise map_lc_error(exc, model=label) from exc
        finally:
            await aclose_stream(agen)
            # Runs on cancel/error too (ADR 0061 §2) — on an aborted
            # stream the estimate covers sent messages + merged partial.
            prompt_messages, completions = _estimate_prompt_and_completions(
                prompts.CHAT, user_prompt, final_messages, acc_box[0],
                aborted=not stream_done,
            )
            _estimate_if_no_usage(
                chat, usage, messages=prompt_messages, completion_messages=completions
            )
            if usage:
                rec.set_usage(usage)
        if session_id:
            await _publish_deltas(session_id, pending, force=True)
        last_ai = _last_ai(final_messages)
        if stream_done and last_ai is not None and isinstance(last_ai.content, str):
            output: str = last_ai.content
        else:
            # Aborted stream (cancel / recursion cap) — the committed
            # snapshot lags the streamed deltas; the partial text is
            # everything that was emitted.
            output = "".join(parts)
        text = output.strip()
        rec.response_text = text or None
    return text or None


OutT = TypeVar("OutT", bound=BaseModel)


def _structured_from_text(out_type: type[OutT], content: Any) -> OutT | None:
    """Plain-text JSON fallback when a model answers instead of calling ``out_type``."""
    if isinstance(content, str):
        text = content
    else:
        text = "".join(str(block.get("text") or "") for block in content if isinstance(block, dict))
    try:
        return out_type.model_validate(omit_nulls(json.loads(text)))
    except (ValueError, TypeError):
        return None


async def run_lc_tool_loop(
    *,
    chat: BaseChatModel,
    system: str,
    user_prompt: str,
    tools: Sequence[Any],
    out_type: type[OutT],
    rec: LlmCallRecordBuilder,
) -> OutT | None:
    """``create_agent`` loop for typed-output harnesses (ADR 0061).

    ``ToolStrategy`` binds ``out_type`` as a tool in the same loop — the
    model interleaves real tool calls and finishes by "calling" the output
    schema in a single model call. A
    no-tool-call reply falls back to parsing its text as JSON. Provider
    errors raise ``LlmProviderError``; everything else (tool bugs,
    validation misses) propagates for the caller's parse-fail path.
    """
    agent = create_agent(
        chat,
        tools=[*tools],
        system_prompt=system,
        response_format=ToolStrategy(out_type),
    )
    try:
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config={"recursion_limit": _RECURSION_LIMIT},
        )
    except asyncio.CancelledError:
        raise
    except GraphRecursionError:
        logger.warning("lc agent hit %s supersteps; parse miss", _RECURSION_LIMIT)
        return None
    except StructuredOutputError:
        # ToolStrategy exhausted its validation retries — a parse miss for
        # the caller, not a provider error (ADR 0061 §3 contract).
        raise
    except Exception as exc:
        raise map_lc_error(exc, model=model_label(chat)) from exc
    messages = list(result.get("messages") or [])
    usage: dict[str, int] = {}
    for message in messages:
        message_usage = getattr(message, "usage_metadata", None)
        if message_usage:
            _merge_lc_usage(usage, message_usage)
    ai_replies = [m for m in messages if isinstance(m, AIMessage)]
    prompt_messages, completions = _estimate_prompt_and_completions(
        system, user_prompt, messages, None
    )
    _estimate_if_no_usage(
        chat, usage, messages=prompt_messages, completion_messages=completions
    )
    if usage:
        rec.set_usage(usage)
    parsed = result.get("structured_response")
    if isinstance(parsed, out_type):
        return parsed
    if parsed is not None:
        return out_type.model_validate(omit_nulls(dict(parsed)))
    last_ai = ai_replies[-1] if ai_replies else None
    return _structured_from_text(out_type, getattr(last_ai, "content", "") if last_ai else "")


async def run_typed_lc_agent(
    *,
    chat: BaseChatModel,
    label: str,
    tier: ModelTier | None,
    system: str,
    user_prompt: str,
    tools: Sequence[Any],
    out_type: type[OutT],
    is_valid: Callable[[OutT], bool],
    log_tag: str,
) -> OutT | None:
    """Recorder + error contract shared by the research/execute LC paths.

    Provider errors raise ``LlmProviderError``, cancels propagate,
    every other failure is a parse miss → ``None``.
    """
    with track(
        kind="chat_json",
        tier=tier,
        model=label,
        system=system,
        user=user_prompt,
    ) as rec:
        try:
            parsed = await run_lc_tool_loop(
                chat=chat,
                system=system,
                user_prompt=user_prompt,
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
        chat, label = _model_override, model_label(_model_override)
    else:
        chat, label = live_lc_chat_model()
    return await _stream_chat_reply_lc(
        chat=chat,
        label=label,
        user_prompt=user_prompt,
        session_id=session_id,
        deps=deps,
        extra_tools=extra_tools,
    )
