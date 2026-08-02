"""Session service: persist rows + invoke LangGraph with DB context."""

from __future__ import annotations

import logging
import secrets
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from internal.llm.router import LlmProviderError
from internal.memory import repos
from internal.memory.models import Session
from internal.session.context import session_db
from internal.session.events import session_event_bus
from internal.session.graph import get_session_graph
from internal.session.state import MODE_CHAT, MODE_PREVIEW
from schemas.contracts import DraftCopy, PreviewUpdatedData

logger = logging.getLogger(__name__)

DEFAULT_PLATFORM = "instagram"


def _extract_llm_provider_error(exc: BaseException) -> LlmProviderError | None:
    cur: BaseException | None = exc
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, LlmProviderError):
            return cur
        cur = cur.__cause__ or cur.__context__
    return None


def _session_config(session_id: uuid.UUID) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(session_id)}}


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
) -> dict[str, Any]:
    return PreviewUpdatedData(
        revision=revision,
        approval_token=approval_token,
        image_url=image_url,
        draft_copy=DraftCopy.model_validate(normalize_draft_copy(copy)),
        platform=platform or DEFAULT_PLATFORM,
    ).model_dump(by_alias=True)


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
        "grounding_ok": state.get("grounding_ok", True),
    }


async def run_session_turn(
    db: AsyncSession,
    session: Session,
    *,
    user_content: str,
) -> dict[str, Any]:
    """Append user message, invoke/resume graph, persist assistant + draft side-effects."""
    user_msg = await repos.add_session_message(
        db, session_id=session.id, role="user", content=user_content
    )
    existing = await repos.list_session_messages(db, session.id)
    message_dicts = [{"role": m.role, "content": m.content} for m in existing]

    graph = get_session_graph()
    config = _session_config(session.id)

    provider_error: LlmProviderError | None = None
    values: dict[str, Any] = {}
    still_interrupted = False
    progress_events: list[dict[str, Any]] = []

    with session_db(db):
        snapshot = await graph.aget_state(config)
        interrupted = bool(snapshot.next)

        session_event_bus.begin_turn_progress(session.id)
        try:
            if interrupted:
                # Resume after interrupt_before=["executor_image_plan"]
                result = await graph.ainvoke(None, config)
            else:
                result = await graph.ainvoke(_graph_values(session, message_dicts), config)

            snapshot = await graph.aget_state(config)
            values = dict(snapshot.values or result or {})
            still_interrupted = bool(snapshot.next)
        except Exception as exc:
            provider_error = _extract_llm_provider_error(exc)
            if provider_error is None:
                raise
            logger.warning(
                "LLM provider error during session turn (session=%s model=%s kind=%s): %s",
                session.id,
                provider_error.model,
                provider_error.kind,
                provider_error.message,
            )
            # Keep whatever checkpoint state exists; do not pretend the turn succeeded.
            snapshot = await graph.aget_state(config)
            values = dict(snapshot.values or {})
            still_interrupted = bool(snapshot.next)
            chinese = any("\u4e00" <= c <= "\u9fff" for c in user_content)
            fail_msg = (
                f"AI 服務暫時唔可用（{provider_error.kind}"
                + (f" · {provider_error.model}" if provider_error.model else "")
                + f"）：{provider_error.message}"
                if chinese
                else (
                    f"AI service unavailable ({provider_error.kind}"
                    + (f" · {provider_error.model}" if provider_error.model else "")
                    + f"): {provider_error.message}"
                )
            )
            values["error"] = provider_error.message
            values["messages"] = list(values.get("messages") or message_dicts) + [
                {"role": "assistant", "content": fail_msg}
            ]
        finally:
            progress_events = session_event_bus.end_turn_progress(session.id)

    # Persist Cursor-style action trail on the user turn that triggered it
    # (session_messages.metadata) so refresh / reopen can rebuild the UI.
    agent_actions = [
        ev.get("data") or {}
        for ev in progress_events
        if ev.get("type") == "agent.progress" and isinstance(ev.get("data"), dict)
    ]
    if agent_actions:
        meta = dict(user_msg.metadata_ or {})
        meta["agent_actions"] = agent_actions
        user_msg.metadata_ = meta
        flag_modified(user_msg, "metadata_")

    prior_count = len(message_dicts)
    new_messages = (values.get("messages") or [])[prior_count:]
    saved_assistant: list = []
    for msg in new_messages:
        if msg.get("role") == "assistant":
            saved_assistant.append(
                await repos.add_session_message(
                    db,
                    session_id=session.id,
                    role="assistant",
                    content=str(msg.get("content") or ""),
                )
            )

    mode = values.get("mode") or session.mode
    session.mode = mode
    session.state = {
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
        "grounding_ok": values.get("grounding_ok", True),
        "error": values.get("error"),
        # UI hydrate: interrupt_before executor_image_plan
        "awaiting_image_ok": still_interrupted,
    }

    events: list[dict[str, Any]] = list(progress_events)
    if provider_error:
        events.append({"type": "llm.failed", "data": provider_error.to_event_data()})
    elif values.get("error"):
        # Node-level LLM failure (e.g. chat) without raising out of the graph.
        # review_exhausted also sets error — keep review.failed for that path.
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
        if still_interrupted:
            events.append(
                {
                    "type": "draft.awaiting_image_ok",
                    "data": {"message": "Resume with another message to generate image"},
                }
            )
        elif values.get("image_url"):
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
                await repos.upsert_preview_draft(
                    db,
                    session_id=session.id,
                    revision=rev,
                    copy=draft_copy,
                    image_url=values.get("image_url"),
                    image_plan=values.get("image_plan"),
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
                            image_url=values.get("image_url"),
                            copy=draft_copy,
                            platform=platform,
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

    await db.flush()
    await session_event_bus.publish_many(session.id, events)
    return {
        "session": session,
        "assistant_messages": saved_assistant,
        "interrupted": still_interrupted,
        "events": events,
        "values": values,
    }


async def update_session_draft(
    db: AsyncSession,
    session: Session,
    *,
    caption: str,
    hashtags: list[str],
    cta: str,
) -> dict[str, Any]:
    """Persist a user manual edit in PREVIEW mode — no LangGraph / LLM turn."""
    if session.mode != MODE_PREVIEW:
        raise ValueError("Session is not in PREVIEW mode")
    if session.status == "confirmed":
        raise ValueError("Session already confirmed")

    state = dict(session.state or {})
    copy = normalize_draft_copy({"caption": caption, "hashtags": hashtags, "cta": cta})
    if not copy["caption"].strip():
        raise ValueError("caption is required")

    existing = await repos.get_latest_preview_draft(db, session.id)
    base_rev = existing.revision if existing else int(state.get("revision") or 0)
    rev = base_rev + 1
    token = secrets.token_urlsafe(24)
    image_url = state.get("image_url") or (existing.image_url if existing else None)
    image_plan = state.get("image_plan") or (existing.image_plan if existing else None)
    source_signal_ids = list(state.get("source_signal_ids") or [])
    if existing and existing.source_signal_ids and not source_signal_ids:
        source_signal_ids = list(existing.source_signal_ids)
    platform = (existing.platform if existing else None) or DEFAULT_PLATFORM

    await repos.upsert_preview_draft(
        db,
        session_id=session.id,
        revision=rev,
        copy=copy,
        image_url=image_url,
        image_plan=image_plan,
        source_signal_ids=source_signal_ids,
        approval_token=token,
        platform=platform,
    )

    state["draft"] = copy
    state["revision"] = rev
    state["approval_token"] = token
    state["image_url"] = image_url
    state["pending_confirm"] = False
    state["need_image"] = False
    session.state = state
    session.mode = MODE_PREVIEW

    graph = get_session_graph()
    config = _session_config(session.id)
    try:
        await graph.aupdate_state(
            config,
            {
                "draft": copy,
                "revision": rev,
                "approval_token": token,
                "image_url": image_url,
                "mode": MODE_PREVIEW,
                "pending_confirm": False,
                "need_image": False,
            },
        )
    except Exception:
        logger.warning(
            "Failed to sync graph checkpoint after manual draft update (session=%s)",
            session.id,
            exc_info=True,
        )

    events = [
        {"type": "draft.copy_updated", "data": copy},
        {
            "type": "preview.updated",
            "data": preview_updated_payload(
                revision=rev,
                approval_token=token,
                image_url=image_url,
                copy=copy,
                platform=platform,
            ),
        },
    ]
    await db.flush()
    await session_event_bus.publish_many(session.id, events)
    return {
        "revision": rev,
        "approval_token": token,
        "copy": copy,
        "image_url": image_url,
        "platform": platform,
        "mode": MODE_PREVIEW,
        "events": events,
    }
