"""History recency: a follow-up turn must bump ``sessions.updated_at``."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from internal.memory.repos import touch_session
from internal.session.service import _persist_after_invoke, run_session_turn
from internal.session.turn_registry import session_turn_registry


@pytest.fixture(autouse=True)
async def _clear_registry():
    session_turn_registry._entries.clear()
    yield
    session_turn_registry._entries.clear()


def _session(*, updated_at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        mode="CHAT",
        status="active",
        state={
            "brief": {},
            "draft": {},
            "image_plan": {},
            "image_url": None,
            "revision": 0,
            "source_signal_ids": [],
            "reviewer_feedback": "",
            "review_attempts": 0,
            "pending_confirm": False,
            "approval_token": None,
            "need_image": False,
            "company_context": {},
            "voice_pack": {},
            "audience_catalog": [],
            "active_persona": None,
            "ranked_signals": [],
            "trend_notes": "",
            "primary_product": None,
            "related_products": [],
            "product_clarify": False,
            "product_context_ids": [],
            "product_candidates": [],
            "grounding_ok": True,
            "error": None,
            "awaiting_image_ok": False,
        },
        updated_at=updated_at,
    )


def test_touch_session_sets_aware_now() -> None:
    session = _session(updated_at=datetime(2026, 1, 1, tzinfo=UTC))
    touch_session(session)
    assert session.updated_at.tzinfo is UTC
    assert session.updated_at > datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_persist_bumps_updated_at_when_state_is_unchanged() -> None:
    """Equal JSONB state would skip SQLAlchemy onupdate — persist must still bump."""
    old = datetime.now(UTC) - timedelta(days=30)
    session = _session(updated_at=old)
    db = AsyncMock()
    values = {
        "mode": "CHAT",
        "messages": [{"role": "user", "content": "hi again"}],
        "brief": {},
        "draft": {},
    }

    with patch(
        "internal.session.service.session_event_bus.publish_many",
        AsyncMock(),
    ):
        await _persist_after_invoke(
            db,
            session,
            user_msg=None,
            message_dicts=[{"role": "user", "content": "hi again"}],
            values=values,
            still_interrupted=False,
            parked_node=None,
            progress_events=[],
            provider_error=None,
            user_content="hi again",
            pre_state=dict(session.state),
            entry=None,
        )

    assert session.updated_at > old
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_run_session_turn_touches_before_graph() -> None:
    """Recency must move even if the later persist writes equal JSONB state."""
    old = datetime.now(UTC) - timedelta(days=30)
    session = _session(updated_at=old)
    db = AsyncMock()
    user_msg = SimpleNamespace(id=uuid.uuid4(), metadata_={})

    async def fake_invoke(*_a, **_k):
        assert session.updated_at > old
        return {}, False, None, None, [], 1

    with (
        patch("internal.session.service.session_is_parked", AsyncMock(return_value=False)),
        patch(
            "internal.session.service.repos.add_session_message",
            AsyncMock(return_value=user_msg),
        ),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch("internal.session.service._invoke_graph", fake_invoke),
        patch(
            "internal.session.service._persist_after_invoke",
            AsyncMock(return_value={}),
        ) as persist,
    ):
        await run_session_turn(db, session, user_content="hi")

    persist.assert_awaited()
    assert session.updated_at > old
