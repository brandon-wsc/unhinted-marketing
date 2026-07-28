"""Session service: persist rows + invoke LangGraph with DB context."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory import repos
from internal.memory.models import Session
from internal.session.context import session_db
from internal.session.events import session_event_bus
from internal.session.graph import get_session_graph
from internal.session.state import MODE_CHAT, MODE_PREVIEW


def _session_config(session_id: uuid.UUID) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(session_id)}}


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
    await repos.add_session_message(
        db, session_id=session.id, role="user", content=user_content
    )
    existing = await repos.list_session_messages(db, session.id)
    message_dicts = [{"role": m.role, "content": m.content} for m in existing]

    graph = get_session_graph()
    config = _session_config(session.id)

    with session_db(db):
        snapshot = await graph.aget_state(config)
        interrupted = bool(snapshot.next)

        if interrupted:
            # Resume after interrupt_before=["executor_image_plan"]
            result = await graph.ainvoke(None, config)
        else:
            result = await graph.ainvoke(_graph_values(session, message_dicts), config)

        snapshot = await graph.aget_state(config)
        values = dict(snapshot.values or result or {})
        still_interrupted = bool(snapshot.next)

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
    }

    events: list[dict[str, Any]] = []
    if values.get("brief"):
        events.append({"type": "brief.updated", "data": values["brief"]})
    if values.get("source_signal_ids"):
        events.append(
            {"type": "signals.updated", "data": {"source_signal_ids": values["source_signal_ids"]}}
        )
    if values.get("draft"):
        events.append({"type": "draft.copy_updated", "data": values["draft"]})
    if values.get("image_plan") and not still_interrupted:
        events.append({"type": "draft.image_plan_updated", "data": values["image_plan"]})
    if still_interrupted:
        events.append(
            {
                "type": "draft.awaiting_image_ok",
                "data": {"message": "Resume with another message to generate image"},
            }
        )
    elif values.get("image_url"):
        events.append({"type": "draft.updated", "data": {"image_url": values["image_url"]}})

    if (
        mode == MODE_PREVIEW
        and values.get("approval_token")
        and values.get("revision")
        and not still_interrupted
    ):
        existing_draft = await repos.get_latest_preview_draft(db, session.id)
        rev = int(values["revision"])
        if not existing_draft or existing_draft.revision < rev:
            await repos.upsert_preview_draft(
                db,
                session_id=session.id,
                revision=rev,
                copy=values.get("draft") or {},
                image_url=values.get("image_url"),
                image_plan=values.get("image_plan"),
                source_signal_ids=values.get("source_signal_ids") or [],
                approval_token=str(values["approval_token"]),
            )
            events.append(
                {
                    "type": "preview.updated",
                    "data": {
                        "revision": rev,
                        "approval_token": values["approval_token"],
                        "image_url": values.get("image_url"),
                    },
                }
            )

    if values.get("pending_confirm"):
        events.append({"type": "confirm.pending", "data": {}})
    if values.get("error"):
        events.append({"type": "review.failed", "data": {"error": values["error"]}})

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
