"""Session service: persist rows + invoke LangGraph with DB context."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from internal.llm.resolve import company_llm_scope
from internal.llm.router import LlmProviderError
from internal.memory import repos
from internal.memory.models import Session
from internal.session.context import session_db
from internal.session.events import session_event_bus
from internal.session.graph import get_session_graph
from internal.session.media import image_format_from_plan, media_item_payload
from internal.session.state import MODE_CHAT, MODE_PREVIEW
from internal.session.trace import turn_trace
from internal.session.turn_registry import TurnEntry, session_turn_registry
from schemas.contracts import DraftCopy, PreviewMediaItem, PreviewUpdatedData

logger = logging.getLogger(__name__)

DEFAULT_PLATFORM = "instagram"


class SessionTurnConflict(Exception):
    """Busy or parked — caller should map to HTTP 409."""

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(detail)


def _extract_llm_provider_error(exc: BaseException) -> LlmProviderError | None:
    cur: BaseException | None = exc
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, LlmProviderError):
            return cur
        cur = cur.__cause__ or cur.__context__
    return None


def _uses_cjk(text: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in text)


def _turn_failure_reply(user_content: str) -> str:
    """User-facing copy when the graph dies for a non-LLM reason."""
    if _uses_cjk(user_content):
        return "呢輪處理失敗，請再試一次。"
    return "This turn failed. Please try again."


def _llm_failure_reply(user_content: str, err: LlmProviderError) -> str:
    extra = f" · {err.model}" if err.model else ""
    if _uses_cjk(user_content):
        return f"AI 服務暫時唔可用（{err.kind}{extra}）：{err.message}"
    return f"AI service unavailable ({err.kind}{extra}): {err.message}"


async def _rollback_quietly(db: AsyncSession, *, session_id: uuid.UUID) -> None:
    """Reset a poisoned request session so persist / HTTP teardown can proceed."""
    try:
        await db.rollback()
    except Exception:
        logger.warning(
            "rollback after session turn failure failed (session=%s)",
            session_id,
            exc_info=True,
        )


def _session_config(session_id: uuid.UUID) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(session_id)}}


def user_turn_metadata(
    existing: dict[str, Any] | None,
    progress_events: list[dict[str, Any]],
    duration_ms: int | None,
) -> dict[str, Any] | None:
    """Merge agent.progress trail + turn wall-clock into user-message metadata.

    Returns None when there is nothing to persist (no user-facing progress).
    """
    actions = [
        ev.get("data") or {}
        for ev in progress_events
        if ev.get("type") == "agent.progress" and isinstance(ev.get("data"), dict)
    ]
    if not actions:
        return None
    meta = dict(existing or {})
    meta["agent_actions"] = actions
    if duration_ms is not None and duration_ms >= 0:
        meta["duration_ms"] = int(duration_ms)
    return meta


def normalize_draft_copy(copy: dict[str, Any] | None) -> dict[str, Any]:
    raw = copy or {}
    hashtags = raw.get("hashtags") or []
    if not isinstance(hashtags, list):
        hashtags = []
    return DraftCopy(
        caption=str(raw.get("caption") or ""),
        hashtags=[str(h) for h in hashtags if str(h).strip()],
        cta=str(raw.get("cta") or ""),
    ).model_dump()


def preview_updated_payload(
    *,
    revision: int,
    approval_token: str,
    image_url: str | None,
    copy: dict[str, Any] | None,
    platform: str | None = None,
    media: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    items = [PreviewMediaItem.model_validate(m) for m in (media or [])]
    primary = image_url
    if primary is None and items:
        primary = items[0].url
    return PreviewUpdatedData(
        revision=revision,
        approval_token=approval_token,
        image_url=primary,
        media=items,
        draft_copy=DraftCopy.model_validate(normalize_draft_copy(copy)),
        platform=platform or DEFAULT_PLATFORM,
    ).model_dump(by_alias=True)


async def _media_for_new_draft(
    db: AsyncSession,
    session: Session,
    *,
    image_url: str | None,
    image_plan: dict[str, Any] | None,
    image_format: str | None,
    reuse_media_ids: list[uuid.UUID] | None,
    create_image_row: bool,
) -> tuple[list[uuid.UUID], list[dict[str, Any]], str | None, dict[str, Any] | None]:
    """Resolve media_ids for a new draft revision (ADR 0008).

    - create_image_row: insert append-only preview_images from url/plan (gen path).
    - else reuse_media_ids: caption-only path keeps same image versions.
    """
    if create_image_row and (image_url or image_plan):
        fmt = image_format_from_plan(
            image_plan, fallback=image_format or "single"
        )
        row = await repos.insert_preview_image(
            db,
            session_id=session.id,
            url=image_url,
            plan=image_plan,
            format=fmt,
            role="primary",
            seq=0,
            status="ready" if image_url else "pending",
        )
        media = [
            media_item_payload(
                image_id=row.id,
                url=row.url,
                plan=row.plan,
                format=row.format,
                role=row.role,
                seq=row.seq,
                status=row.status,
            )
        ]
        return [row.id], media, row.url, dict(row.plan or {})

    ids = list(reuse_media_ids or [])
    rows = await repos.get_preview_images_by_ids(db, ids)
    media = [
        media_item_payload(
            image_id=r.id,
            url=r.url,
            plan=r.plan,
            format=r.format,
            role=r.role,
            seq=r.seq,
            status=r.status,
        )
        for r in rows
    ]
    primary_url = media[0]["url"] if media else image_url
    primary_plan = media[0]["plan"] if media else image_plan
    return ids, media, primary_url, primary_plan


def _graph_values(session: Session, messages: list[dict[str, Any]]) -> dict[str, Any]:
    state = dict(session.state or {})
    return {
        "messages": messages,
        "mode": session.mode or MODE_CHAT,
        "company_id": str(session.company_id),
        "user_id": str(session.user_id),
        "thread_id": str(session.id),
        "brief": state.get("brief") or {},
        "draft": state.get("draft") or {},
        "image_plan": state.get("image_plan") or {},
        "image_url": state.get("image_url"),
        "revision": state.get("revision") or 0,
        "source_signal_ids": state.get("source_signal_ids") or [],
        "reviewer_feedback": state.get("reviewer_feedback") or "",
        "review_attempts": state.get("review_attempts") or 0,
        "pending_confirm": state.get("pending_confirm") or False,
        "approval_token": state.get("approval_token"),
        "need_image": state.get("need_image", False),
        "company_context": state.get("company_context") or {},
        "voice_pack": state.get("voice_pack") or {},
        "audience_catalog": state.get("audience_catalog") or [],
        "active_persona": state.get("active_persona"),
        "ranked_signals": state.get("ranked_signals") or [],
        "trend_notes": state.get("trend_notes") or "",
        "primary_product": state.get("primary_product"),
        "related_products": state.get("related_products") or [],
        "product_clarify": bool(state.get("product_clarify")),
        "product_context_ids": state.get("product_context_ids") or [],
        "product_candidates": state.get("product_candidates") or [],
        "grounding_ok": state.get("grounding_ok", True),
    }


def _strip_discard_meta(state: dict[str, Any] | None) -> dict[str, Any]:
    out = copy.deepcopy(state or {})
    out.pop("turn_discard", None)
    out.pop("awaiting_image_ok", None)
    return out


@dataclass
class ForkPreviewCopy:
    """Facts about a fork's preview copy, for the route to derive preview_note."""

    copied: bool
    copied_revision: int | None
    latest_revision: int | None


async def copy_session_preview(
    db: AsyncSession,
    source: Session,
    target: Session,
    *,
    as_of: datetime | None = None,
) -> ForkPreviewCopy:
    """Copy the source's preview draft + media into a forked session (ADR 0017).

    With ``as_of`` (the fork-point message's created_at) the copy is
    time-aligned: the revision that existed at that moment, or nothing when the
    preview postdates the fork point. The fork restarts at revision=1 with a
    freshly minted approval_token — tokens are never shared across sessions
    (ADR 0003). preview_images rows are duplicated into the target session
    (append-only per ADR 0008; same asset URLs) and media_ids are remapped to
    the new row ids. The copied draft keeps the source row's created_at so the
    timeline stays aligned for fork-of-fork.
    """
    latest = await repos.get_latest_preview_draft(db, source.id)
    draft = (
        await repos.get_preview_draft_as_of(db, source.id, as_of)
        if as_of is not None
        else latest
    )
    latest_revision = latest.revision if latest is not None else None
    if draft is None:
        return ForkPreviewCopy(
            copied=False, copied_revision=None, latest_revision=latest_revision
        )

    id_map: dict[uuid.UUID, uuid.UUID] = {}
    for img in await repos.get_preview_images_by_ids(db, list(draft.media_ids or [])):
        row = await repos.insert_preview_image(
            db,
            session_id=target.id,
            url=img.url,
            plan=img.plan,
            format=img.format,
            role=img.role,
            seq=img.seq,
            status=img.status,
        )
        id_map[img.id] = row.id
    media_ids = [id_map[i] for i in (draft.media_ids or []) if i in id_map]

    token = secrets.token_urlsafe(24)
    await repos.upsert_preview_draft(
        db,
        session_id=target.id,
        revision=1,
        copy=copy.deepcopy(draft.copy or {}),
        image_url=draft.image_url,
        image_plan=copy.deepcopy(draft.image_plan) if draft.image_plan else None,
        source_signal_ids=list(draft.source_signal_ids or []),
        approval_token=token,
        platform=draft.platform,
        media_ids=media_ids,
        created_at=draft.created_at,
    )

    state: dict[str, Any] = {
        "draft": copy.deepcopy(draft.copy or {}),
        "revision": 1,
        "approval_token": token,
        "image_url": draft.image_url,
        "media_ids": [str(i) for i in media_ids],
        "pending_confirm": False,
        "need_image": False,
        "awaiting_image_ok": False,
    }
    if draft.image_plan is not None:
        state["image_plan"] = copy.deepcopy(draft.image_plan)
    target.state = state
    if source.mode == MODE_PREVIEW:
        target.mode = MODE_PREVIEW
    return ForkPreviewCopy(
        copied=True, copied_revision=draft.revision, latest_revision=latest_revision
    )


async def graph_is_parked(session_id: uuid.UUID) -> bool:
    graph = get_session_graph()
    snapshot = await graph.aget_state(_session_config(session_id))
    return bool(snapshot.next)


async def session_is_parked(session: Session) -> bool:
    if bool((session.state or {}).get("awaiting_image_ok")):
        return True
    try:
        return await graph_is_parked(session.id)
    except Exception:
        logger.debug("Could not read graph interrupt state", exc_info=True)
        return False


async def _adelete_graph_thread(session_id: uuid.UUID) -> None:
    graph = get_session_graph()
    saver = getattr(graph, "checkpointer", None)
    if saver is None:
        return
    delete = getattr(saver, "adelete_thread", None)
    if delete is None:
        return
    try:
        await delete(str(session_id))
    except Exception:
        logger.warning(
            "Failed to adelete_thread for session=%s",
            session_id,
            exc_info=True,
        )


async def _repark_graph_at_image_interrupt(
    db: AsyncSession,
    session: Session,
) -> None:
    """After cancelling resume-image, wipe mid-run checkpoint and re-seat interrupt.

    ``aupdate_state(..., as_node="reviewer")`` with ``need_image=True`` schedules
    ``executor_image_plan``, which pauses again via ``interrupt_before``.
    """
    await _adelete_graph_thread(session.id)
    msgs = await repos.list_session_messages(db, session.id)
    message_dicts = [{"role": m.role, "content": m.content} for m in msgs]
    values = _graph_values(session, message_dicts)
    values["need_image"] = True
    values["reviewer_passed"] = True
    graph = get_session_graph()
    config = _session_config(session.id)
    try:
        await graph.aupdate_state(config, values, as_node="reviewer")
    except Exception:
        logger.warning(
            "Failed to re-park graph at image interrupt (session=%s)",
            session.id,
            exc_info=True,
        )


async def _discard_turn_state(
    db: AsyncSession,
    session: Session,
    *,
    pre_state: dict[str, Any],
    message_ids: list[uuid.UUID],
) -> None:
    """Restore pre-turn session.state, delete turn messages, wipe graph thread."""
    session_event_bus.end_turn_progress(session.id)
    restored = _strip_discard_meta(pre_state)
    restored["awaiting_image_ok"] = False
    session.state = restored
    if message_ids:
        await repos.delete_session_messages_by_ids(db, session.id, message_ids)
    await _adelete_graph_thread(session.id)
    await db.flush()
    await session_event_bus.publish_many(
        session.id,
        [{"type": "turn.cancelled", "data": {"reason": "stop", "awaiting_image_ok": False}}],
    )


async def _restore_parked_after_resume_cancel(
    db: AsyncSession,
    session: Session,
    *,
    parked_state: dict[str, Any],
    message_ids: list[uuid.UUID],
) -> None:
    """Cancel in-flight resume-image: keep draft/brief and re-show Generate-image CTA."""
    session_event_bus.end_turn_progress(session.id)
    restored = copy.deepcopy(parked_state)
    restored["awaiting_image_ok"] = True
    session.state = restored
    if message_ids:
        await repos.delete_session_messages_by_ids(db, session.id, message_ids)
    await _repark_graph_at_image_interrupt(db, session)
    await db.flush()
    await session_event_bus.publish_many(
        session.id,
        [{"type": "turn.cancelled", "data": {"reason": "stop", "awaiting_image_ok": True}}],
    )


async def _persist_after_invoke(
    db: AsyncSession,
    session: Session,
    *,
    user_msg: Any | None,
    message_dicts: list[dict[str, Any]],
    values: dict[str, Any],
    still_interrupted: bool,
    progress_events: list[dict[str, Any]],
    provider_error: LlmProviderError | None,
    user_content: str,
    pre_state: dict[str, Any],
    entry: TurnEntry | None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    if user_msg is not None:
        meta = user_turn_metadata(user_msg.metadata_ or {}, progress_events, duration_ms)
        if meta is not None:
            user_msg.metadata_ = meta
            flag_modified(user_msg, "metadata_")

    prior_count = len(message_dicts)
    new_messages = (values.get("messages") or [])[prior_count:]
    saved_assistant: list = []
    for msg in new_messages:
        if msg.get("role") == "assistant":
            saved = await repos.add_session_message(
                db,
                session_id=session.id,
                role="assistant",
                content=str(msg.get("content") or ""),
            )
            saved_assistant.append(saved)
            if entry is not None:
                session_turn_registry.track_message(session.id, saved.id)

    mode = values.get("mode") or session.mode
    session.mode = mode
    next_state: dict[str, Any] = {
        "brief": values.get("brief") or {},
        "draft": values.get("draft") or {},
        "image_plan": values.get("image_plan") or {},
        "image_url": values.get("image_url"),
        "revision": values.get("revision") or 0,
        "source_signal_ids": values.get("source_signal_ids") or [],
        "reviewer_feedback": values.get("reviewer_feedback") or "",
        "review_attempts": values.get("review_attempts") or 0,
        "pending_confirm": values.get("pending_confirm") or False,
        "approval_token": values.get("approval_token"),
        "need_image": values.get("need_image", False),
        "company_context": values.get("company_context") or {},
        "voice_pack": values.get("voice_pack") or {},
        "audience_catalog": values.get("audience_catalog") or [],
        "active_persona": values.get("active_persona"),
        "ranked_signals": values.get("ranked_signals") or [],
        "trend_notes": values.get("trend_notes") or "",
        "primary_product": values.get("primary_product"),
        "related_products": values.get("related_products") or [],
        "product_clarify": bool(values.get("product_clarify")),
        "product_context_ids": values.get("product_context_ids") or [],
        "product_candidates": values.get("product_candidates") or [],
        "grounding_ok": values.get("grounding_ok", True),
        "error": values.get("error"),
        # UI hydrate: interrupt_before executor_image_plan
        "awaiting_image_ok": still_interrupted,
    }
    if still_interrupted:
        if user_msg is not None:
            next_state["turn_discard"] = {
                "pre_state": _strip_discard_meta(pre_state),
                "user_message_id": str(user_msg.id),
                "message_ids": [
                    str(mid) for mid in (entry.message_ids if entry else [user_msg.id])
                ],
            }
        elif isinstance((session.state or {}).get("turn_discard"), dict):
            # resume-image: keep the original park discard metadata (ADR 0004).
            next_state["turn_discard"] = dict(session.state["turn_discard"])
    session.state = next_state

    events: list[dict[str, Any]] = list(progress_events)
    if provider_error:
        events.append({"type": "llm.failed", "data": provider_error.to_event_data()})
    elif values.get("error"):
        err = str(values["error"])
        if "Reviewer failed" in err:
            events.append({"type": "review.failed", "data": {"error": err}})
        else:
            events.append(
                {
                    "type": "llm.failed",
                    "data": {"error": err, "kind": "provider"},
                }
            )

    if still_interrupted:
        events.append(
            {
                "type": "draft.awaiting_image_ok",
                "data": {"awaiting": True},
            }
        )

    if not provider_error:
        if values.get("brief"):
            events.append({"type": "brief.updated", "data": values["brief"]})
        if values.get("source_signal_ids"):
            events.append(
                {
                    "type": "signals.updated",
                    "data": {"source_signal_ids": values["source_signal_ids"]},
                }
            )
        if values.get("draft"):
            events.append({"type": "draft.copy_updated", "data": values["draft"]})
        if values.get("image_plan") and not still_interrupted:
            events.append(
                {"type": "draft.image_plan_updated", "data": values["image_plan"]}
            )
        if not still_interrupted and values.get("image_url"):
            events.append(
                {"type": "draft.updated", "data": {"image_url": values["image_url"]}}
            )

        if (
            mode == MODE_PREVIEW
            and values.get("approval_token")
            and values.get("revision")
            and not still_interrupted
        ):
            existing_draft = await repos.get_latest_preview_draft(db, session.id)
            rev = int(values["revision"])
            if not existing_draft or existing_draft.revision < rev:
                platform = (
                    existing_draft.platform if existing_draft else None
                ) or DEFAULT_PLATFORM
                draft_copy = normalize_draft_copy(values.get("draft"))
                media_ids, media, primary_url, primary_plan = await _media_for_new_draft(
                    db,
                    session,
                    image_url=values.get("image_url"),
                    image_plan=values.get("image_plan")
                    if isinstance(values.get("image_plan"), dict)
                    else None,
                    image_format=values.get("image_format")
                    if isinstance(values.get("image_format"), str)
                    else None,
                    reuse_media_ids=None,
                    create_image_row=True,
                )
                await repos.upsert_preview_draft(
                    db,
                    session_id=session.id,
                    revision=rev,
                    copy=draft_copy,
                    image_url=primary_url,
                    image_plan=primary_plan,
                    media_ids=media_ids,
                    source_signal_ids=values.get("source_signal_ids") or [],
                    approval_token=str(values["approval_token"]),
                    platform=platform,
                )
                events.append(
                    {
                        "type": "preview.updated",
                        "data": preview_updated_payload(
                            revision=rev,
                            approval_token=str(values["approval_token"]),
                            image_url=primary_url,
                            copy=draft_copy,
                            platform=platform,
                            media=media,
                        ),
                    }
                )

        if values.get("pending_confirm"):
            events.append({"type": "confirm.pending", "data": {}})

    for msg in saved_assistant:
        events.append(
            {
                "type": "message.assistant",
                "data": {"id": str(msg.id), "content": msg.content},
            }
        )

    repos.touch_session(session)
    await db.flush()
    await session_event_bus.publish_many(session.id, events)
    return {
        "session": session,
        "assistant_messages": saved_assistant,
        "interrupted": still_interrupted,
        "events": events,
        "values": values,
    }


async def _invoke_graph(
    db: AsyncSession,
    session: Session,
    *,
    graph_input: dict[str, Any] | None,
    user_content: str,
    message_dicts: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool, LlmProviderError | None, list[dict[str, Any]], int]:
    # Capture PKs before invoke — a failed node can expire the ORM row, and
    # lazy-loading session.id in except/finally then masks the original error.
    session_id = session.id
    user_id = session.user_id
    company_id = session.company_id
    graph = get_session_graph()
    config = _session_config(session_id)
    provider_error: LlmProviderError | None = None
    values: dict[str, Any] = {}
    still_interrupted = False
    progress_events: list[dict[str, Any]] = []
    started = time.perf_counter()

    async with company_llm_scope(db, company_id):
        with (
            session_db(db),
            turn_trace(
                session_id=session_id,
                user_id=user_id,
                company_id=company_id,
            ),
        ):
            session_event_bus.begin_turn_progress(session_id)
            try:
                result = await graph.ainvoke(graph_input, config)
                snapshot = await graph.aget_state(config)
                values = dict(snapshot.values or result or {})
                still_interrupted = bool(snapshot.next)
            except asyncio.CancelledError:
                progress_events = session_event_bus.end_turn_progress(session_id)
                raise
            except Exception as exc:
                provider_error = _extract_llm_provider_error(exc)
                if provider_error is None:
                    logger.exception("Session turn failed (session=%s)", session_id)
                    await _rollback_quietly(db, session_id=session_id)
                    fail_msg = _turn_failure_reply(user_content)
                    values = {
                        "error": fail_msg,
                        "messages": list(message_dicts)
                        + [{"role": "assistant", "content": fail_msg}],
                    }
                    still_interrupted = False
                else:
                    logger.warning(
                        "LLM provider error during session turn "
                        "(session=%s model=%s kind=%s): %s",
                        session_id,
                        provider_error.model,
                        provider_error.kind,
                        provider_error.message,
                    )
                    try:
                        snapshot = await graph.aget_state(config)
                        values = dict(snapshot.values or {})
                        still_interrupted = bool(snapshot.next)
                    except Exception:
                        logger.exception(
                            "aget_state after LLM error failed (session=%s)",
                            session_id,
                        )
                        values = {}
                        still_interrupted = False
                    values["error"] = provider_error.message
                    values["messages"] = list(values.get("messages") or message_dicts) + [
                        {
                            "role": "assistant",
                            "content": _llm_failure_reply(user_content, provider_error),
                        }
                    ]
            finally:
                if not progress_events:
                    progress_events = session_event_bus.end_turn_progress(session_id)

    duration_ms = max(0, int((time.perf_counter() - started) * 1000))
    return values, still_interrupted, provider_error, progress_events, duration_ms


async def run_session_turn(
    db: AsyncSession,
    session: Session,
    *,
    user_content: str,
    source_question_id: str | None = None,
) -> dict[str, Any]:
    """Append user message, invoke graph (never blind-resume), persist side-effects."""
    session_id = session.id
    if session_turn_registry.is_busy(session_id):
        raise SessionTurnConflict("busy", "Session turn already in progress")
    if await session_is_parked(session):
        raise SessionTurnConflict(
            "parked",
            "Session is awaiting image confirmation — use resume-image or stop",
        )

    pre_state = _strip_discard_meta(session.state)
    user_msg = await repos.add_session_message(
        db, session_id=session_id, role="user", content=user_content
    )
    repos.touch_session(session)
    existing = await repos.list_session_messages(db, session_id)
    message_dicts = [{"role": m.role, "content": m.content} for m in existing]
    graph_input = _graph_values(session, message_dicts)
    if source_question_id:
        item = await repos.get_question_item(db, session.company_id, source_question_id)
        refs = [str(sid) for sid in (item or {}).get("source_signal_ids") or [] if sid]
        if refs:
            graph_input["source_signal_ids"] = refs
            graph_input["handoff_signal_ids"] = refs

    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("run_session_turn requires a running asyncio task")
    entry = await session_turn_registry.begin(
        session_id,
        task=task,
        pre_state=pre_state,
        user_message_id=user_msg.id,
    )

    try:
        (
            values,
            still_interrupted,
            provider_error,
            progress_events,
            duration_ms,
        ) = await _invoke_graph(
            db,
            session,
            graph_input=graph_input,
            user_content=user_content,
            message_dicts=message_dicts,
        )
        return await _persist_after_invoke(
            db,
            session,
            user_msg=user_msg,
            message_dicts=message_dicts,
            values=values,
            still_interrupted=still_interrupted,
            progress_events=progress_events,
            provider_error=provider_error,
            user_content=user_content,
            pre_state=pre_state,
            entry=entry,
            duration_ms=duration_ms,
        )
    except asyncio.CancelledError:
        await _discard_turn_state(
            db,
            session,
            pre_state=entry.pre_state,
            message_ids=list(entry.message_ids),
        )
        # Commit before signaling Stop waiters (separate request/session).
        await db.commit()
        entry.discarded.set()
        raise
    finally:
        if not entry.cancelling:
            await session_turn_registry.clear(session_id, entry=entry)


async def resume_image_turn(
    db: AsyncSession,
    session: Session,
    *,
    image_format: str | None = None,
) -> dict[str, Any]:
    """Resume parked graph at interrupt_before executor_image_plan (ADR 0004)."""
    session_id = session.id
    if session_turn_registry.is_busy(session_id):
        raise SessionTurnConflict("busy", "Session turn already in progress")
    if not await session_is_parked(session):
        raise SessionTurnConflict("not_parked", "Session is not awaiting image confirmation")

    # Snapshot full parked UI state so Stop mid-image can restore the CTA.
    parked_restore = copy.deepcopy(dict(session.state or {}))
    parked_restore["awaiting_image_ok"] = True
    repos.touch_session(session)

    existing = await repos.list_session_messages(db, session_id)
    message_dicts = [{"role": m.role, "content": m.content} for m in existing]
    # Synthetic id for registry bookkeeping (no new user row on resume).
    resume_msg_id = uuid.uuid4()

    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("resume_image_turn requires a running asyncio task")
    entry = await session_turn_registry.begin(
        session_id,
        task=task,
        pre_state=_strip_discard_meta(parked_restore),
        user_message_id=resume_msg_id,
    )
    entry.kind = "resume_image"
    entry.parked_restore = parked_restore
    # Resume must not delete prior user messages on stop — only assistants added now.
    entry.message_ids = []

    try:
        if image_format is not None:
            from internal.session.image_format import normalize_image_format

            fmt = normalize_image_format(image_format)
            graph = get_session_graph()
            config = _session_config(session_id)
            await graph.aupdate_state(config, {"image_format": fmt})
            st = dict(session.state or {})
            st["image_format"] = fmt
            session.state = st
            await db.flush()

        (
            values,
            still_interrupted,
            provider_error,
            progress_events,
            duration_ms,
        ) = await _invoke_graph(
            db,
            session,
            graph_input=None,
            user_content="",
            message_dicts=message_dicts,
        )
        if provider_error:
            # Keep Generate-image CTA so Retry can POST /resume-image instead of
            # a new chat turn. Checkpoint after a failed gen node may have no
            # interrupt; re-seat like Stop mid-resume.
            still_interrupted = True
            values = {
                **_strip_discard_meta(parked_restore),
                **values,
                "need_image": True,
                "error": values.get("error") or provider_error.message,
                "messages": values.get("messages") or message_dicts,
            }
        result = await _persist_after_invoke(
            db,
            session,
            user_msg=None,
            message_dicts=message_dicts,
            values=values,
            still_interrupted=still_interrupted,
            progress_events=progress_events,
            provider_error=provider_error,
            user_content="",
            pre_state=_strip_discard_meta(parked_restore),
            entry=entry,
            duration_ms=duration_ms,
        )
        if provider_error:
            await _repark_graph_at_image_interrupt(db, session)
            parked = dict(session.state or {})
            parked["awaiting_image_ok"] = True
            session.state = parked
            result["interrupted"] = True
        return result
    except asyncio.CancelledError:
        await _restore_parked_after_resume_cancel(
            db,
            session,
            parked_state=entry.parked_restore or parked_restore,
            message_ids=list(entry.message_ids),
        )
        await db.commit()
        entry.discarded.set()
        raise
    finally:
        if not entry.cancelling:
            await session_turn_registry.clear(session_id, entry=entry)


async def stop_session_turn(
    db: AsyncSession,
    session: Session,
) -> dict[str, Any]:
    """Cancel in-flight turn or discard parked interrupt (ADR 0004).

    Stopping mid ``resume-image`` re-parks at the image interrupt (CTA returns).
    Stopping a normal message turn or an idle parked session discards the turn.
    """
    entry = session_turn_registry.get(session.id)
    if entry is not None and not entry.task.done():
        if entry.cancelling:
            await entry.discarded.wait()
            await db.refresh(session)
            awaiting = bool((session.state or {}).get("awaiting_image_ok"))
            return {
                "status": "cancelled",
                "interrupted": awaiting,
                "awaiting_image_ok": awaiting,
            }
        entry.cancelling = True
        entry.task.cancel()
        try:
            await asyncio.wait_for(entry.discarded.wait(), timeout=60.0)
        except TimeoutError:
            logger.error("Timed out waiting for turn discard (session=%s)", session.id)
            if not entry.discarded.is_set():
                if entry.kind == "resume_image" and entry.parked_restore is not None:
                    await _restore_parked_after_resume_cancel(
                        db,
                        session,
                        parked_state=entry.parked_restore,
                        message_ids=list(entry.message_ids),
                    )
                else:
                    await _discard_turn_state(
                        db,
                        session,
                        pre_state=entry.pre_state,
                        message_ids=list(entry.message_ids),
                    )
                entry.discarded.set()
        await session_turn_registry.clear(session.id, entry=entry)
        await db.refresh(session)
        awaiting = bool((session.state or {}).get("awaiting_image_ok"))
        return {
            "status": "cancelled",
            "interrupted": awaiting,
            "awaiting_image_ok": awaiting,
        }

    # Parked discard (no in-flight task) — drop the agent turn that created the draft.
    if await session_is_parked(session):
        state = dict(session.state or {})
        anchor = state.get("turn_discard") if isinstance(state.get("turn_discard"), dict) else {}
        pre_state = anchor.get("pre_state") if isinstance(anchor.get("pre_state"), dict) else {}
        pre_state = _strip_discard_meta(pre_state)
        message_ids: list[uuid.UUID] = []
        raw_ids = anchor.get("message_ids") or []
        if isinstance(raw_ids, list):
            for raw in raw_ids:
                try:
                    message_ids.append(uuid.UUID(str(raw)))
                except ValueError:
                    continue
        if not message_ids and anchor.get("user_message_id"):
            with contextlib.suppress(ValueError):
                message_ids.append(uuid.UUID(str(anchor["user_message_id"])))
        await _discard_turn_state(
            db,
            session,
            pre_state=pre_state,
            message_ids=message_ids,
        )
        return {
            "status": "cancelled",
            "interrupted": False,
            "awaiting_image_ok": False,
        }

    return {"status": "idle", "interrupted": False, "awaiting_image_ok": False}


async def update_session_draft(
    db: AsyncSession,
    session: Session,
    *,
    caption: str,
    hashtags: list[str],
    cta: str,
) -> dict[str, Any]:
    """Persist a user manual caption edit in PREVIEW mode — no LangGraph / LLM turn."""
    if session.mode != MODE_PREVIEW:
        raise ValueError("Session is not in PREVIEW mode")

    state = dict(session.state or {})
    copy = normalize_draft_copy({"caption": caption, "hashtags": hashtags, "cta": cta})
    if not copy["caption"].strip():
        raise ValueError("caption is required")

    existing = await repos.get_latest_preview_draft(db, session.id)
    # Caption-only: reuse media_ids (ADR 0008). Do not invent a new image row.
    reuse_ids = list(existing.media_ids or []) if existing else []
    media_ids, media, primary_url, primary_plan = await _media_for_new_draft(
        db,
        session,
        image_url=state.get("image_url") or (existing.image_url if existing else None),
        image_plan=state.get("image_plan")
        if isinstance(state.get("image_plan"), dict)
        else (existing.image_plan if existing else None),
        image_format=None,
        reuse_media_ids=reuse_ids,
        create_image_row=False,
    )
    # Legacy drafts without media_ids but with image_url: create one image once.
    if not media_ids and (primary_url or primary_plan):
        media_ids, media, primary_url, primary_plan = await _media_for_new_draft(
            db,
            session,
            image_url=primary_url,
            image_plan=primary_plan if isinstance(primary_plan, dict) else None,
            image_format=None,
            reuse_media_ids=None,
            create_image_row=True,
        )
    return await _bump_preview_revision(
        db,
        session,
        media_ids=media_ids,
        media=media,
        primary_url=primary_url,
        primary_plan=primary_plan if isinstance(primary_plan, dict) else None,
        copy=copy,
    )


async def _bump_preview_revision(
    db: AsyncSession,
    session: Session,
    *,
    media_ids: list[uuid.UUID],
    media: list[dict[str, Any]],
    primary_url: str | None,
    primary_plan: dict[str, Any] | None,
    copy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a new preview_drafts row + sync session.state / SSE (ADR 0008)."""
    if session.status == "confirmed":
        raise ValueError("Session already confirmed")

    state = dict(session.state or {})
    existing = await repos.get_latest_preview_draft(db, session.id)
    draft_copy = normalize_draft_copy(
        copy if copy is not None else (existing.copy if existing else state.get("draft"))
    )
    if not draft_copy["caption"].strip():
        raise ValueError("caption is required")

    base_rev = existing.revision if existing else int(state.get("revision") or 0)
    rev = base_rev + 1
    token = secrets.token_urlsafe(24)
    source_signal_ids = list(state.get("source_signal_ids") or [])
    if existing and existing.source_signal_ids and not source_signal_ids:
        source_signal_ids = list(existing.source_signal_ids)
    platform = (existing.platform if existing else None) or DEFAULT_PLATFORM

    await repos.upsert_preview_draft(
        db,
        session_id=session.id,
        revision=rev,
        copy=draft_copy,
        image_url=primary_url,
        image_plan=primary_plan,
        media_ids=media_ids,
        source_signal_ids=source_signal_ids,
        approval_token=token,
        platform=platform,
    )

    state["draft"] = draft_copy
    state["revision"] = rev
    state["approval_token"] = token
    state["image_url"] = primary_url
    if primary_plan is not None:
        state["image_plan"] = primary_plan
    state["media_ids"] = [str(i) for i in media_ids]
    state["pending_confirm"] = False
    state["need_image"] = False
    state["awaiting_image_ok"] = False
    state.pop("turn_discard", None)
    session.state = state
    session.mode = MODE_PREVIEW

    graph = get_session_graph()
    config = _session_config(session.id)
    try:
        await graph.aupdate_state(
            config,
            {
                "draft": draft_copy,
                "revision": rev,
                "approval_token": token,
                "image_url": primary_url,
                "image_plan": primary_plan or {},
                "mode": MODE_PREVIEW,
                "pending_confirm": False,
                "need_image": False,
            },
        )
    except Exception:
        logger.warning(
            "Failed to sync graph checkpoint after preview revision (session=%s)",
            session.id,
            exc_info=True,
        )

    events = [
        {"type": "draft.copy_updated", "data": draft_copy},
        {
            "type": "preview.updated",
            "data": preview_updated_payload(
                revision=rev,
                approval_token=token,
                image_url=primary_url,
                copy=draft_copy,
                platform=platform,
                media=media,
            ),
        },
    ]
    await db.flush()
    await session_event_bus.publish_many(session.id, events)
    return {
        "revision": rev,
        "approval_token": token,
        "copy": draft_copy,
        "image_url": primary_url,
        "media": media,
        "platform": platform,
        "mode": MODE_PREVIEW,
        "events": events,
    }


async def list_latest_session_media(
    db: AsyncSession, session: Session
) -> list[dict[str, Any]]:
    draft = await repos.get_latest_preview_draft(db, session.id)
    ids = list(draft.media_ids or []) if draft else []
    if not ids:
        state_ids = (session.state or {}).get("media_ids") or []
        ids = [uuid.UUID(str(i)) for i in state_ids]
    rows = await repos.get_preview_images_by_ids(db, ids)
    return [
        media_item_payload(
            image_id=r.id,
            url=r.url,
            plan=r.plan,
            format=r.format,
            role=r.role,
            seq=r.seq,
            status=r.status,
        )
        for r in rows
    ]


def _replace_media_id(
    media_ids: list[uuid.UUID], old_id: uuid.UUID, new_id: uuid.UUID
) -> list[uuid.UUID]:
    return [new_id if i == old_id else i for i in media_ids]


async def update_session_image_plan(
    db: AsyncSession,
    session: Session,
    *,
    image_id: uuid.UUID,
    plan: dict[str, Any],
) -> dict[str, Any]:
    """User edits plan → new image row + new draft (no LLM)."""
    if session.mode != MODE_PREVIEW:
        raise ValueError("Session is not in PREVIEW mode")
    existing = await repos.get_latest_preview_draft(db, session.id)
    if not existing:
        raise ValueError("No preview draft yet")
    media_ids = list(existing.media_ids or [])
    if image_id not in media_ids:
        raise ValueError("Image is not part of the current draft")
    old = await repos.get_preview_image(db, image_id)
    if old is None or old.session_id != session.id:
        raise ValueError("Image not found")

    fmt = image_format_from_plan(plan, fallback=old.format)
    new_plan = dict(plan)
    new_plan["format"] = fmt
    row = await repos.insert_preview_image(
        db,
        session_id=session.id,
        url=old.url,
        plan=new_plan,
        format=fmt,
        role=old.role,
        seq=old.seq,
        status=old.status if old.url else "pending",
    )
    new_ids = _replace_media_id(media_ids, image_id, row.id)
    rows = await repos.get_preview_images_by_ids(db, new_ids)
    media = [
        media_item_payload(
            image_id=r.id,
            url=r.url,
            plan=r.plan,
            format=r.format,
            role=r.role,
            seq=r.seq,
            status=r.status,
        )
        for r in rows
    ]
    primary = media[0] if media else None
    return await _bump_preview_revision(
        db,
        session,
        media_ids=new_ids,
        media=media,
        primary_url=primary["url"] if primary else None,
        primary_plan=primary["plan"] if primary else None,
    )


async def regen_session_image(
    db: AsyncSession,
    session: Session,
    *,
    image_id: uuid.UUID,
) -> dict[str, Any]:
    """Regenerate image from current plan → new image row + new draft."""
    from internal.llm.router import (
        LlmProviderError,
        generate_image,
        has_llm_credentials,
        resolve_image_model,
    )
    from internal.media.storage import media_object_key, persist_generated_image
    from internal.session.image_format import compose_generation_prompt

    if session.mode != MODE_PREVIEW:
        raise ValueError("Session is not in PREVIEW mode")
    existing = await repos.get_latest_preview_draft(db, session.id)
    if not existing:
        raise ValueError("No preview draft yet")
    media_ids = list(existing.media_ids or [])
    if image_id not in media_ids:
        raise ValueError("Image is not part of the current draft")
    old = await repos.get_preview_image(db, image_id)
    if old is None or old.session_id != session.id:
        raise ValueError("Image not found")

    plan = dict(old.plan or {})
    fmt = image_format_from_plan(plan, fallback=old.format)
    plan["format"] = fmt
    prompt = compose_generation_prompt(plan)
    if not prompt:
        prompt = f"Clean modern social media image for Hong Kong brand, format={fmt}"

    async with company_llm_scope(db, session.company_id):
        image_model = resolve_image_model()
        if not has_llm_credentials() or (image_model and image_model.lower() == "placeholder"):
            url = f"placeholder://local/{session.id}/regen-{secrets.token_hex(4)}.png"
        elif not image_model:
            raise LlmProviderError(
                "No image model configured (set LLM_IMAGE_MODEL).",
                kind="unsupported",
            )
        else:
            raw_ref = await generate_image(prompt=prompt)
            rev = (existing.revision if existing else 0) + 1
            key = media_object_key(session_id=str(session.id), revision=rev)
            url = await persist_generated_image(raw_ref, key=key)

    row = await repos.insert_preview_image(
        db,
        session_id=session.id,
        url=url,
        plan=plan,
        format=fmt,
        role=old.role,
        seq=old.seq,
        status="ready",
    )
    new_ids = _replace_media_id(media_ids, image_id, row.id)
    rows = await repos.get_preview_images_by_ids(db, new_ids)
    media = [
        media_item_payload(
            image_id=r.id,
            url=r.url,
            plan=r.plan,
            format=r.format,
            role=r.role,
            seq=r.seq,
            status=r.status,
        )
        for r in rows
    ]
    primary = media[0] if media else None
    return await _bump_preview_revision(
        db,
        session,
        media_ids=new_ids,
        media=media,
        primary_url=primary["url"] if primary else None,
        primary_plan=primary["plan"] if primary else None,
    )


async def add_session_image(
    db: AsyncSession,
    session: Session,
    *,
    format: str = "single",
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a new image slot (pending plan) → new image row + new draft."""
    if session.mode != MODE_PREVIEW:
        raise ValueError("Session is not in PREVIEW mode")
    existing = await repos.get_latest_preview_draft(db, session.id)
    if not existing:
        raise ValueError("No preview draft yet")
    media_ids = list(existing.media_ids or [])
    fmt = image_format_from_plan(plan, fallback=format)
    new_plan = dict(plan or {})
    new_plan.setdefault("format", fmt)
    if fmt == "comic_4panel" and not new_plan.get("panels"):
        new_plan["panels"] = [
            {"index": 1, "beat": "hook scene — no product"},
            {"index": 2, "beat": "escalate friction"},
            {"index": 3, "beat": "peak pain"},
            {"index": 4, "beat": "product as soft remedy"},
        ]
    seq = len(media_ids)
    row = await repos.insert_preview_image(
        db,
        session_id=session.id,
        url=None,
        plan=new_plan,
        format=fmt,
        role="primary" if seq == 0 else "extra",
        seq=seq,
        status="pending",
    )
    new_ids = media_ids + [row.id]
    rows = await repos.get_preview_images_by_ids(db, new_ids)
    media = [
        media_item_payload(
            image_id=r.id,
            url=r.url,
            plan=r.plan,
            format=r.format,
            role=r.role,
            seq=r.seq,
            status=r.status,
        )
        for r in rows
    ]
    primary = media[0] if media else None
    return await _bump_preview_revision(
        db,
        session,
        media_ids=new_ids,
        media=media,
        primary_url=primary["url"] if primary else None,
        primary_plan=primary["plan"] if primary else None,
    )


_UPLOAD_MAX_BYTES = 10 * 1024 * 1024
_UPLOAD_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


async def remove_session_image(
    db: AsyncSession,
    session: Session,
    *,
    image_id: uuid.UUID,
) -> dict[str, Any]:
    """Remove image id from current draft media_ids → new draft (orphan row OK)."""
    if session.mode != MODE_PREVIEW:
        raise ValueError("Session is not in PREVIEW mode")
    existing = await repos.get_latest_preview_draft(db, session.id)
    if not existing:
        raise ValueError("No preview draft yet")
    media_ids = list(existing.media_ids or [])
    if image_id not in media_ids:
        raise ValueError("Image is not part of the current draft")
    if len(media_ids) <= 1:
        raise ValueError("Cannot remove the last remaining image")
    new_ids = [i for i in media_ids if i != image_id]
    rows = await repos.get_preview_images_by_ids(db, new_ids)
    media = [
        media_item_payload(
            image_id=r.id,
            url=r.url,
            plan=r.plan,
            format=r.format,
            role=r.role,
            seq=r.seq,
            status=r.status,
        )
        for r in rows
    ]
    primary = media[0] if media else None
    return await _bump_preview_revision(
        db,
        session,
        media_ids=new_ids,
        media=media,
        primary_url=primary["url"] if primary else None,
        primary_plan=primary["plan"] if primary else None,
    )


async def upload_session_image(
    db: AsyncSession,
    session: Session,
    *,
    image_id: uuid.UUID,
    data: bytes,
    content_type: str,
) -> dict[str, Any]:
    """Upload user image → new preview_images row + replace slot in draft."""
    from internal.media.storage import (
        MediaStorageError,
        ensure_bucket,
        media_object_key,
        media_storage_configured,
        put_bytes,
    )

    if session.mode != MODE_PREVIEW:
        raise ValueError("Session is not in PREVIEW mode")
    existing = await repos.get_latest_preview_draft(db, session.id)
    if not existing:
        raise ValueError("No preview draft yet")
    media_ids = list(existing.media_ids or [])
    if image_id not in media_ids:
        raise ValueError("Image is not part of the current draft")
    old = await repos.get_preview_image(db, image_id)
    if old is None or old.session_id != session.id:
        raise ValueError("Image not found")

    ct = (content_type or "").split(";", 1)[0].strip().lower()
    ext = _UPLOAD_CONTENT_TYPES.get(ct)
    if not ext:
        raise ValueError("File must be an image (jpeg, png, webp, or gif)")
    if not data:
        raise ValueError("Empty upload")
    if len(data) > _UPLOAD_MAX_BYTES:
        raise ValueError("Image too large (max 10MB)")

    plan = dict(old.plan or {})
    fmt = image_format_from_plan(plan, fallback=old.format)
    plan["format"] = fmt

    if media_storage_configured():
        rev = (existing.revision if existing else 0) + 1
        key = media_object_key(session_id=str(session.id), revision=rev, ext=ext)
        try:
            await ensure_bucket()
            url = await put_bytes(key=key, data=data, content_type=ct)
        except MediaStorageError as exc:
            raise MediaStorageError(str(exc)) from exc
    else:
        # Dev/tests without S3 — keep a renderable-enough placeholder URL.
        url = f"placeholder://local/{session.id}/upload-{secrets.token_hex(4)}.{ext}"

    row = await repos.insert_preview_image(
        db,
        session_id=session.id,
        url=url,
        plan=plan,
        format=fmt,
        role=old.role,
        seq=old.seq,
        status="ready",
    )
    new_ids = _replace_media_id(media_ids, image_id, row.id)
    rows = await repos.get_preview_images_by_ids(db, new_ids)
    media = [
        media_item_payload(
            image_id=r.id,
            url=r.url,
            plan=r.plan,
            format=r.format,
            role=r.role,
            seq=r.seq,
            status=r.status,
        )
        for r in rows
    ]
    primary = media[0] if media else None
    return await _bump_preview_revision(
        db,
        session,
        media_ids=new_ids,
        media=media,
        primary_url=primary["url"] if primary else None,
        primary_plan=primary["plan"] if primary else None,
    )
