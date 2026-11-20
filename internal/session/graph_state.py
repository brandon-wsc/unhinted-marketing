"""Graph invoke config and persisted session-state helpers shared by session services."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from internal.memory.models import Session
from internal.session.state import MODE_CHAT


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
        "chosen_persona": state.get("chosen_persona"),
        "image_format": state.get("image_format"),
        "chosen_image_format": state.get("chosen_image_format"),
        # ADR 0047 — last persisted digests carry over; run_session_turn
        # refreshes them from the attachment_sessions join each message turn.
        "attachments": list(state.get("attachments") or []),
        # ADR 0057 — rolling recap pair; summary_upto counts folded messages.
        "thread_summary": state.get("thread_summary") or "",
        "summary_upto": state.get("summary_upto") or 0,
    }


def _strip_discard_meta(state: dict[str, Any] | None) -> dict[str, Any]:
    out = copy.deepcopy(state or {})
    out.pop("turn_discard", None)
    out.pop("awaiting_image_ok", None)
    out.pop("awaiting_angle_pick", None)
    return out
