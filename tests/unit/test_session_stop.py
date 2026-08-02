"""Unit tests for ADR 0004 stop / parked / resume conflict paths."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from internal.session.service import (
    SessionTurnConflict,
    resume_image_turn,
    run_session_turn,
    stop_session_turn,
)
from internal.session.turn_registry import session_turn_registry


@pytest.fixture(autouse=True)
async def _clear_registry():
    # Ensure no cross-test busy slots.
    session_turn_registry._entries.clear()
    yield
    session_turn_registry._entries.clear()


def _session(*, awaiting: bool = False, turn_discard: dict | None = None) -> SimpleNamespace:
    state: dict = {}
    if awaiting:
        state["awaiting_image_ok"] = True
    if turn_discard is not None:
        state["turn_discard"] = turn_discard
    return SimpleNamespace(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        mode="AGENT",
        status="active",
        state=state,
    )


@pytest.mark.asyncio
async def test_run_session_turn_rejects_when_parked() -> None:
    session = _session(awaiting=True)
    db = AsyncMock()
    with pytest.raises(SessionTurnConflict) as exc:
        await run_session_turn(db, session, user_content="hello")
    assert exc.value.reason == "parked"


@pytest.mark.asyncio
async def test_run_session_turn_rejects_when_busy() -> None:
    session = _session()
    db = AsyncMock()

    async def _blocker() -> None:
        await asyncio.sleep(60)

    task = asyncio.create_task(_blocker())
    await session_turn_registry.begin(
        session.id,
        task=task,
        pre_state={},
        user_message_id=uuid.uuid4(),
    )
    try:
        with pytest.raises(SessionTurnConflict) as exc:
            await run_session_turn(db, session, user_content="hello")
        assert exc.value.reason == "busy"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await session_turn_registry.clear(session.id)


@pytest.mark.asyncio
async def test_resume_image_rejects_when_not_parked() -> None:
    session = _session(awaiting=False)
    db = AsyncMock()
    with (
        patch("internal.session.service.graph_is_parked", AsyncMock(return_value=False)),
        pytest.raises(SessionTurnConflict) as exc,
    ):
        await resume_image_turn(db, session)
    assert exc.value.reason == "not_parked"


@pytest.mark.asyncio
async def test_stop_idle_is_noop() -> None:
    session = _session(awaiting=False)
    db = AsyncMock()
    with patch("internal.session.service.session_is_parked", AsyncMock(return_value=False)):
        result = await stop_session_turn(db, session)
    assert result == {
        "status": "idle",
        "interrupted": False,
        "awaiting_image_ok": False,
    }

@pytest.mark.asyncio
async def test_stop_parked_discards_messages_and_state() -> None:
    user_msg_id = uuid.uuid4()
    session = _session(
        awaiting=True,
        turn_discard={
            "pre_state": {"brief": {}, "draft": {}},
            "user_message_id": str(user_msg_id),
            "message_ids": [str(user_msg_id)],
        },
    )
    db = AsyncMock()

    with (
        patch("internal.session.service.session_is_parked", AsyncMock(return_value=True)),
        patch(
            "internal.session.service.repos.delete_session_messages_by_ids",
            AsyncMock(return_value=1),
        ) as delete_msgs,
        patch(
            "internal.session.service._adelete_graph_thread",
            AsyncMock(),
        ) as delete_thread,
        patch(
            "internal.session.service.session_event_bus.publish_many",
            AsyncMock(),
        ) as publish,
    ):
        result = await stop_session_turn(db, session)

    assert result == {
        "status": "cancelled",
        "interrupted": False,
        "awaiting_image_ok": False,
    }
    assert session.state.get("awaiting_image_ok") is False
    assert "turn_discard" not in (session.state or {})
    delete_msgs.assert_awaited()
    delete_thread.assert_awaited_once()
    publish.assert_awaited()
    events = publish.await_args.args[1]
    assert events[0]["type"] == "turn.cancelled"
    assert events[0]["data"]["awaiting_image_ok"] is False


@pytest.mark.asyncio
async def test_stop_mid_resume_image_reparks() -> None:
    """Stop during resume-image restores parked CTA (does not discard agent turn)."""
    session = _session(
        awaiting=True,
        turn_discard={
            "pre_state": {"brief": {"summary": "x"}},
            "user_message_id": str(uuid.uuid4()),
            "message_ids": [],
        },
    )
    # Mimic parked draft still on session when resume starts.
    session.state["draft"] = {"caption": "hi", "hashtags": [], "cta": ""}
    session.state["brief"] = {"summary": "x", "can_do": [], "cannot_do": [], "angles": []}

    db = AsyncMock()
    started = asyncio.Event()
    cancelled_ok = asyncio.Event()

    async def _slow_invoke(*_a, **_k):
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled_ok.set()
            raise
        return {}, False, None, []

    with (
        patch("internal.session.service.session_is_parked", AsyncMock(return_value=True)),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch(
            "internal.session.service._invoke_graph",
            side_effect=_slow_invoke,
        ),
        patch(
            "internal.session.service._restore_parked_after_resume_cancel",
            AsyncMock(),
        ) as restore,
        patch(
            "internal.session.service._adelete_graph_thread",
            AsyncMock(),
        ),
    ):
        resume_task = asyncio.create_task(resume_image_turn(db, session))
        await asyncio.wait_for(started.wait(), timeout=2.0)
        # Simulate concurrent Stop while resume is in-flight.
        stop_result = await stop_session_turn(db, session)
        with pytest.raises(asyncio.CancelledError):
            await resume_task

    assert cancelled_ok.is_set()
    restore.assert_awaited()
    # stop returns after discard; session.state may still be pre-restore mock —
    # assert stop payload when restore mutates real state via helper.
    assert stop_result["status"] == "cancelled"
    assert stop_result["awaiting_image_ok"] is True
    assert stop_result["interrupted"] is True


@pytest.mark.asyncio
async def test_restore_parked_after_resume_cancel_sets_flag() -> None:
    from internal.session.service import _restore_parked_after_resume_cancel

    session = _session(awaiting=False)
    parked = {
        "awaiting_image_ok": True,
        "brief": {"summary": "keep"},
        "draft": {"caption": "c", "hashtags": [], "cta": ""},
        "turn_discard": {"pre_state": {}, "message_ids": []},
    }
    db = AsyncMock()
    with (
        patch(
            "internal.session.service.repos.delete_session_messages_by_ids",
            AsyncMock(return_value=0),
        ),
        patch(
            "internal.session.service._repark_graph_at_image_interrupt",
            AsyncMock(),
        ) as repark,
        patch(
            "internal.session.service.session_event_bus.publish_many",
            AsyncMock(),
        ) as publish,
    ):
        await _restore_parked_after_resume_cancel(
            db,
            session,
            parked_state=parked,
            message_ids=[],
        )

    assert session.state["awaiting_image_ok"] is True
    assert session.state["brief"]["summary"] == "keep"
    assert "turn_discard" in session.state
    repark.assert_awaited_once()
    events = publish.await_args.args[1]
    assert events[0]["data"]["awaiting_image_ok"] is True
