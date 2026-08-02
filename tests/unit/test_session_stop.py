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
    with patch("internal.session.service.graph_is_parked", AsyncMock(return_value=False)):
        with pytest.raises(SessionTurnConflict) as exc:
            await resume_image_turn(db, session)
    assert exc.value.reason == "not_parked"


@pytest.mark.asyncio
async def test_stop_idle_is_noop() -> None:
    session = _session(awaiting=False)
    db = AsyncMock()
    with patch("internal.session.service.session_is_parked", AsyncMock(return_value=False)):
        result = await stop_session_turn(db, session)
    assert result == {"status": "idle"}


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

    assert result == {"status": "cancelled"}
    assert session.state.get("awaiting_image_ok") is False
    assert "turn_discard" not in (session.state or {})
    delete_msgs.assert_awaited()
    delete_thread.assert_awaited_once()
    publish.assert_awaited()
    events = publish.await_args.args[1]
    assert events[0]["type"] == "turn.cancelled"
