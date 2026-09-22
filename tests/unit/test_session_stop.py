"""Unit tests for ADR 0004 stop / parked / resume conflict paths."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from internal.session.service import (
    SessionTurnConflict,
    choose_angle_turn,
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
        "awaiting_angle_pick": False,
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
        "awaiting_angle_pick": False,
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
async def test_stop_interrupt_keeps_messages_and_salvages_partial() -> None:
    """mode=interrupt cancels but keeps the turn's rows (ADR 0035)."""
    session = _session()
    db = AsyncMock()
    user_msg = SimpleNamespace(
        id=uuid.uuid4(), role="user", content="hi", metadata_={}
    )
    salvaged = SimpleNamespace(id=uuid.uuid4())
    started = asyncio.Event()

    async def _slow_invoke(*_a, **_k):
        started.set()
        await asyncio.sleep(60)

    snapshot = SimpleNamespace(
        values={
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "寫到一半"},
            ]
        }
    )
    graph = SimpleNamespace(aget_state=AsyncMock(return_value=snapshot))

    with (
        patch(
            "internal.session.service.graph_parked_node",
            AsyncMock(return_value=None),
        ),
        patch(
            "internal.session.service.repos.add_session_message",
            AsyncMock(side_effect=[user_msg, salvaged]),
        ) as add_msg,
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[user_msg]),
        ),
        patch("internal.session.service._invoke_graph", side_effect=_slow_invoke),
        patch("internal.session.service.get_session_graph", return_value=graph),
        patch(
            "internal.session.service._adelete_graph_thread",
            AsyncMock(),
        ) as delete_thread,
        patch(
            "internal.session.service.repos.delete_session_messages_by_ids",
            AsyncMock(),
        ) as delete_msgs,
        patch(
            "internal.session.service.session_event_bus.publish_many",
            AsyncMock(),
        ) as publish,
    ):
        turn_task = asyncio.create_task(
            run_session_turn(db, session, user_content="hi")
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)
        result = await stop_session_turn(db, session, mode="interrupt")
        with pytest.raises(asyncio.CancelledError):
            await turn_task

    assert result["status"] == "cancelled"
    assert result["kept"] is True
    delete_msgs.assert_not_awaited()
    delete_thread.assert_awaited_once()
    # user row + salvaged completed-node assistant reply both persisted.
    assert add_msg.await_count == 2
    assert add_msg.await_args_list[1].kwargs["role"] == "assistant"
    assert add_msg.await_args_list[1].kwargs["content"] == "寫到一半"
    assert user_msg.metadata_["interrupted"] is True
    events = publish.await_args.args[1]
    assert events[0]["type"] == "turn.cancelled"
    assert events[0]["data"]["reason"] == "interrupt"
    assert events[0]["data"]["kept"] is True


@pytest.mark.asyncio
async def test_stop_discard_still_wipes_in_flight_turn() -> None:
    """Default mode keeps ADR 0004 discard semantics."""
    session = _session()
    db = AsyncMock()
    user_msg = SimpleNamespace(
        id=uuid.uuid4(), role="user", content="hi", metadata_={}
    )
    started = asyncio.Event()

    async def _slow_invoke(*_a, **_k):
        started.set()
        await asyncio.sleep(60)

    with (
        patch(
            "internal.session.service.graph_parked_node",
            AsyncMock(return_value=None),
        ),
        patch(
            "internal.session.service.repos.add_session_message",
            AsyncMock(return_value=user_msg),
        ),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[user_msg]),
        ),
        patch("internal.session.service._invoke_graph", side_effect=_slow_invoke),
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
        turn_task = asyncio.create_task(
            run_session_turn(db, session, user_content="hi")
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)
        result = await stop_session_turn(db, session)
        with pytest.raises(asyncio.CancelledError):
            await turn_task

    assert result["status"] == "cancelled"
    assert result["kept"] is False
    delete_msgs.assert_awaited_once()
    delete_thread.assert_awaited_once()
    events = publish.await_args.args[1]
    assert events[0]["data"]["reason"] == "stop"
    assert events[0]["data"].get("kept") is not True


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
        return {}, False, None, None, [], 0

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
async def test_resume_image_provider_error_keeps_parked() -> None:
    """Image-gen LLM error must re-park so Retry can resume-image, not send a new turn."""
    from internal.llm.router import LlmProviderError

    discard = {
        "pre_state": {"brief": {"summary": "x"}},
        "user_message_id": str(uuid.uuid4()),
        "message_ids": [],
    }
    session = _session(awaiting=True, turn_discard=discard)
    session.state["draft"] = {"caption": "hi", "hashtags": [], "cta": ""}
    session.state["brief"] = {"summary": "x", "can_do": [], "cannot_do": [], "angles": []}
    err = LlmProviderError("bad model", model="img", kind="bad_request")
    db = AsyncMock()
    persist_kwargs: dict = {}

    async def fake_persist(_db, sess, **kwargs):
        persist_kwargs.update(kwargs)
        sess.state = {
            **dict(sess.state or {}),
            "awaiting_image_ok": kwargs["still_interrupted"],
            "error": err.message,
        }
        return {
            "interrupted": kwargs["still_interrupted"],
            "values": kwargs["values"],
            "events": [],
        }

    with (
        patch("internal.session.service.session_is_parked", AsyncMock(return_value=True)),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch(
            "internal.session.service._invoke_graph",
            AsyncMock(return_value=({}, False, None, err, [], 10)),
        ),
        patch("internal.session.service._persist_after_invoke", fake_persist),
        patch(
            "internal.session.service._repark_graph_at_image_interrupt",
            AsyncMock(),
        ) as repark,
    ):
        result = await resume_image_turn(db, session)

    assert persist_kwargs["still_interrupted"] is True
    assert persist_kwargs["provider_error"] is err
    repark.assert_awaited_once()
    assert result["interrupted"] is True
    assert session.state["awaiting_image_ok"] is True


@pytest.mark.asyncio
async def test_persist_resume_keeps_turn_discard_and_emits_parked_on_llm_error() -> None:
    from internal.llm.router import LlmProviderError
    from internal.session.service import _persist_after_invoke

    discard = {
        "pre_state": {"brief": {"summary": "keep"}},
        "user_message_id": str(uuid.uuid4()),
        "message_ids": [],
    }
    session = _session(awaiting=True, turn_discard=discard)
    session.state["draft"] = {"caption": "hi", "hashtags": [], "cta": ""}
    err = LlmProviderError("nope", model="img", kind="bad_request")
    db = AsyncMock()
    published: list = []

    with patch(
        "internal.session.service.session_event_bus.publish_many",
        AsyncMock(side_effect=lambda _sid, evs: published.extend(evs)),
    ):
        await _persist_after_invoke(
            db,
            session,
            user_msg=None,
            message_dicts=[],
            values={"error": err.message, "messages": [], "draft": session.state["draft"]},
            still_interrupted=True,
            parked_node="executor_image_plan",
            progress_events=[],
            provider_error=err,
            user_content="",
            pre_state={"draft": session.state["draft"]},
            entry=None,
        )

    assert session.state["awaiting_image_ok"] is True
    assert session.state["turn_discard"] == discard
    types = [e["type"] for e in published]
    assert "llm.failed" in types
    assert "draft.awaiting_image_ok" in types


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


def _angle_parked_session() -> SimpleNamespace:
    session = _session(
        turn_discard={
            "pre_state": {"brief": {}},
            "user_message_id": str(uuid.uuid4()),
            "message_ids": [],
        }
    )
    session.state["awaiting_angle_pick"] = True
    session.state["brief"] = {
        "summary": "x",
        "can_do": [],
        "cannot_do": [],
        "angles": ["用情侶日常帶出產品", "數據懶人包"],
        "persona": "hk_youth",
    }
    session.state["audience_catalog"] = [
        {"slug": "hk_youth", "label": "年輕人", "hook": "brunch"},
        {"slug": "hk_parents", "label": "家長", "hook": "school run"},
    ]
    return session


@pytest.mark.asyncio
async def test_run_session_turn_parked_at_angle_is_the_pick() -> None:
    """Typed reply while angle-parked routes to choose-angle, not a new turn."""
    session = _angle_parked_session()
    db = AsyncMock()
    with (
        patch(
            "internal.session.service.choose_angle_turn",
            AsyncMock(return_value={"ok": True}),
        ) as choose,
    ):
        result = await run_session_turn(db, session, user_content="第二個")

    choose.assert_awaited_once()
    assert choose.await_args.kwargs["angle_text"] == "第二個"
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_choose_angle_rejects_when_not_parked() -> None:
    session = _session(awaiting=False)
    db = AsyncMock()
    with pytest.raises(SessionTurnConflict) as exc:
        await choose_angle_turn(db, session, angle_index=0)
    assert exc.value.reason == "not_parked"


@pytest.mark.asyncio
async def test_choose_angle_index_out_of_range() -> None:
    session = _angle_parked_session()
    db = AsyncMock()
    with pytest.raises(ValueError, match="out of range"):
        await choose_angle_turn(db, session, angle_index=5)


@pytest.mark.asyncio
async def test_choose_angle_updates_state_and_resumes() -> None:
    session = _angle_parked_session()
    db = AsyncMock()
    graph = SimpleNamespace(aupdate_state=AsyncMock())

    async def fake_invoke(*_a, **_k):
        # Resumed graph parks at the image gate after drafting.
        return (
            {"mode": "AGENT", "messages": [], "draft": {"caption": "c"}},
            True,
            "executor_image_plan",
            None,
            [],
            5,
        )

    with (
        patch(
            "internal.session.service.get_session_graph",
            return_value=graph,
        ),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch("internal.session.service._invoke_graph", side_effect=fake_invoke),
        patch(
            "internal.session.service._persist_after_invoke",
            AsyncMock(return_value={"interrupted": True, "events": [], "values": {}}),
        ) as persist,
    ):
        result = await choose_angle_turn(db, session, angle_index=1)

    update = graph.aupdate_state.await_args
    assert update.args[1]["chosen_angle"] == "數據懶人包"
    assert "chosen_persona" not in update.args[1]
    assert persist.await_args.kwargs["user_msg"] is None
    assert persist.await_args.kwargs["parked_node"] == "executor_image_plan"
    assert result["interrupted"] is True


@pytest.mark.asyncio
async def test_choose_angle_persona_updates_state() -> None:
    session = _angle_parked_session()
    db = AsyncMock()
    graph = SimpleNamespace(aupdate_state=AsyncMock())

    async def fake_invoke(*_a, **_k):
        return ({"mode": "AGENT", "messages": []}, False, None, None, [], 5)

    with (
        patch(
            "internal.session.service.get_session_graph",
            return_value=graph,
        ),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch("internal.session.service._invoke_graph", side_effect=fake_invoke),
        patch(
            "internal.session.service._persist_after_invoke",
            AsyncMock(return_value={"interrupted": False, "events": [], "values": {}}),
        ),
    ):
        await choose_angle_turn(
            db, session, angle_index=0, persona="hk_parents"
        )

    update = graph.aupdate_state.await_args
    assert update.args[1]["chosen_angle"] == "用情侶日常帶出產品"
    assert update.args[1]["chosen_persona"] == "hk_parents"


@pytest.mark.asyncio
async def test_choose_angle_unknown_persona_rejected() -> None:
    session = _angle_parked_session()
    db = AsyncMock()
    with pytest.raises(ValueError, match="persona is not in the offered catalog"):
        await choose_angle_turn(db, session, angle_index=0, persona="nope")


@pytest.mark.asyncio
async def test_choose_angle_free_text_creates_user_row() -> None:
    session = _angle_parked_session()
    db = AsyncMock()
    graph = SimpleNamespace(aupdate_state=AsyncMock())
    user_msg = SimpleNamespace(id=uuid.uuid4(), metadata_={})

    async def fake_invoke(*_a, **_k):
        return ({"mode": "AGENT", "messages": []}, False, None, None, [], 5)

    with (
        patch(
            "internal.session.service.get_session_graph",
            return_value=graph,
        ),
        patch(
            "internal.session.service.repos.add_session_message",
            AsyncMock(return_value=user_msg),
        ) as add_msg,
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch("internal.session.service._invoke_graph", side_effect=fake_invoke),
        patch(
            "internal.session.service._persist_after_invoke",
            AsyncMock(return_value={"interrupted": False, "events": [], "values": {}}),
        ),
    ):
        await choose_angle_turn(db, session, angle_text="做數據懶人包")

    add_msg.assert_awaited_once()
    assert add_msg.await_args.kwargs["content"] == "做數據懶人包"
    update = graph.aupdate_state.await_args
    assert update.args[1]["chosen_angle"] == "做數據懶人包"


@pytest.mark.asyncio
async def test_choose_angle_retry_does_not_duplicate_user_row() -> None:
    """Re-issuing a failed typed pick must not append a second user bubble."""
    session = _angle_parked_session()
    db = AsyncMock()
    graph = SimpleNamespace(aupdate_state=AsyncMock())
    pick_row = SimpleNamespace(
        id=uuid.uuid4(), role="user", content="做數據懶人包", metadata_={}
    )

    async def fake_invoke(*_a, **_k):
        return ({"mode": "AGENT", "messages": []}, False, None, None, [], 5)

    with (
        patch(
            "internal.session.service.get_session_graph",
            return_value=graph,
        ),
        patch(
            "internal.session.service.repos.add_session_message",
            AsyncMock(),
        ) as add_msg,
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[pick_row]),
        ),
        patch("internal.session.service._invoke_graph", side_effect=fake_invoke),
        patch(
            "internal.session.service._persist_after_invoke",
            AsyncMock(return_value={"interrupted": False, "events": [], "values": {}}),
        ),
    ):
        await choose_angle_turn(db, session, angle_text="做數據懶人包")

    add_msg.assert_not_awaited()
    update = graph.aupdate_state.await_args
    assert update.args[1]["chosen_angle"] == "做數據懶人包"


@pytest.mark.asyncio
async def test_choose_angle_provider_error_reparks() -> None:
    from internal.llm.router import LlmProviderError

    session = _angle_parked_session()
    err = LlmProviderError("nope", model="x", kind="bad_request")
    db = AsyncMock()
    graph = SimpleNamespace(aupdate_state=AsyncMock())
    persist_kwargs: dict = {}

    async def fake_persist(_db, sess, **kwargs):
        persist_kwargs.update(kwargs)
        sess.state = {
            **dict(sess.state or {}),
            "awaiting_angle_pick": kwargs["still_interrupted"],
        }
        return {"interrupted": kwargs["still_interrupted"], "values": {}, "events": []}

    with (
        patch(
            "internal.session.service.get_session_graph",
            return_value=graph,
        ),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch(
            "internal.session.service._invoke_graph",
            AsyncMock(return_value=({}, False, None, err, [], 10)),
        ),
        patch("internal.session.service._persist_after_invoke", fake_persist),
        patch(
            "internal.session.service._repark_graph_at_angle_gate",
            AsyncMock(),
        ) as repark,
    ):
        result = await choose_angle_turn(db, session, angle_index=0)

    assert persist_kwargs["still_interrupted"] is True
    assert persist_kwargs["parked_node"] == "angle_gate"
    repark.assert_awaited_once()
    assert result["interrupted"] is True
    assert session.state["awaiting_angle_pick"] is True


@pytest.mark.asyncio
async def test_stop_mid_choose_angle_reparks() -> None:
    """Stop during choose-angle restores the angle card (does not discard)."""
    session = _angle_parked_session()
    db = AsyncMock()
    graph = SimpleNamespace(aupdate_state=AsyncMock())
    started = asyncio.Event()
    cancelled_ok = asyncio.Event()

    async def _slow_invoke(*_a, **_k):
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled_ok.set()
            raise
        return {}, False, None, None, [], 0

    with (
        patch(
            "internal.session.service.get_session_graph",
            return_value=graph,
        ),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch("internal.session.service._invoke_graph", side_effect=_slow_invoke),
        patch(
            "internal.session.service._restore_parked_after_resume_cancel",
            AsyncMock(),
        ) as restore,
        patch(
            "internal.session.service._adelete_graph_thread",
            AsyncMock(),
        ),
    ):
        pick_task = asyncio.create_task(
            choose_angle_turn(db, session, angle_index=0)
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)
        stop_result = await stop_session_turn(db, session)
        with pytest.raises(asyncio.CancelledError):
            await pick_task

    assert cancelled_ok.is_set()
    restore.assert_awaited()
    assert restore.await_args.kwargs["kind"] == "angle"
    assert stop_result["status"] == "cancelled"
    assert stop_result["interrupted"] is True
    assert stop_result["awaiting_angle_pick"] is True


@pytest.mark.asyncio
async def test_persist_emits_awaiting_angle_pick_event() -> None:
    from internal.session.service import _persist_after_invoke

    session = _angle_parked_session()
    brief = session.state["brief"]
    db = AsyncMock()
    published: list = []

    with patch(
        "internal.session.service.session_event_bus.publish_many",
        AsyncMock(side_effect=lambda _sid, evs: published.extend(evs)),
    ):
        await _persist_after_invoke(
            db,
            session,
            user_msg=None,
            message_dicts=[],
            values={
                "messages": [],
                "brief": brief,
                "audience_catalog": session.state["audience_catalog"],
            },
            still_interrupted=True,
            parked_node="angle_gate",
            progress_events=[],
            provider_error=None,
            user_content="",
            pre_state={},
            entry=None,
        )

    assert session.state["awaiting_angle_pick"] is True
    assert session.state["awaiting_image_ok"] is False
    types = [e["type"] for e in published]
    assert "draft.awaiting_angle_pick" in types
    ev = next(e for e in published if e["type"] == "draft.awaiting_angle_pick")
    assert ev["data"]["awaiting"] is True
    assert ev["data"]["angles"] == brief["angles"]
    assert ev["data"]["personas"] == session.state["audience_catalog"]
    assert ev["data"]["recommended_persona"] == "hk_youth"


# --- ADR 0030 — image_format on the bundled card ----------------------------


@pytest.mark.asyncio
async def test_choose_angle_image_format_updates_state() -> None:
    session = _angle_parked_session()
    db = AsyncMock()
    graph = SimpleNamespace(aupdate_state=AsyncMock())

    async def fake_invoke(*_a, **_k):
        return ({"mode": "AGENT", "messages": []}, False, None, None, [], 5)

    with (
        patch(
            "internal.session.service.get_session_graph",
            return_value=graph,
        ),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch("internal.session.service._invoke_graph", side_effect=fake_invoke),
        patch(
            "internal.session.service._persist_after_invoke",
            AsyncMock(return_value={"interrupted": False, "events": [], "values": {}}),
        ),
    ):
        await choose_angle_turn(db, session, angle_index=0, image_format="comic_4panel")

    update = graph.aupdate_state.await_args
    assert update.args[1]["chosen_angle"] == "用情侶日常帶出產品"
    assert update.args[1]["chosen_image_format"] == "comic_4panel"


@pytest.mark.asyncio
async def test_choose_angle_omitted_format_not_in_update() -> None:
    """Omit ≠ reset (ADR 0030 §2) — no format field, no state touch."""
    session = _angle_parked_session()
    db = AsyncMock()
    graph = SimpleNamespace(aupdate_state=AsyncMock())

    async def fake_invoke(*_a, **_k):
        return ({"mode": "AGENT", "messages": []}, False, None, None, [], 5)

    with (
        patch(
            "internal.session.service.get_session_graph",
            return_value=graph,
        ),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch("internal.session.service._invoke_graph", side_effect=fake_invoke),
        patch(
            "internal.session.service._persist_after_invoke",
            AsyncMock(return_value={"interrupted": False, "events": [], "values": {}}),
        ),
    ):
        await choose_angle_turn(db, session, angle_index=0)

    update = graph.aupdate_state.await_args
    assert "chosen_image_format" not in update.args[1]


@pytest.mark.asyncio
async def test_choose_angle_junk_format_normalized() -> None:
    """Direct service calls bypass Pydantic — normalize defensively."""
    session = _angle_parked_session()
    db = AsyncMock()
    graph = SimpleNamespace(aupdate_state=AsyncMock())

    async def fake_invoke(*_a, **_k):
        return ({"mode": "AGENT", "messages": []}, False, None, None, [], 5)

    with (
        patch(
            "internal.session.service.get_session_graph",
            return_value=graph,
        ),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch("internal.session.service._invoke_graph", side_effect=fake_invoke),
        patch(
            "internal.session.service._persist_after_invoke",
            AsyncMock(return_value={"interrupted": False, "events": [], "values": {}}),
        ),
    ):
        await choose_angle_turn(db, session, angle_index=0, image_format="nope")

    update = graph.aupdate_state.await_args
    assert update.args[1]["chosen_image_format"] == "single"


@pytest.mark.asyncio
async def test_choose_angle_provider_error_keeps_format_sticky() -> None:
    """Provider error re-parks; the submitted format pick is never cleared."""
    from internal.llm.router import LlmProviderError

    session = _angle_parked_session()
    err = LlmProviderError("nope", model="x", kind="bad_request")
    db = AsyncMock()
    graph = SimpleNamespace(aupdate_state=AsyncMock())

    async def fake_persist(_db, sess, **kwargs):
        sess.state = {
            **dict(sess.state or {}),
            "awaiting_angle_pick": kwargs["still_interrupted"],
        }
        return {"interrupted": kwargs["still_interrupted"], "values": {}, "events": []}

    with (
        patch(
            "internal.session.service.get_session_graph",
            return_value=graph,
        ),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch(
            "internal.session.service._invoke_graph",
            AsyncMock(return_value=({}, False, None, err, [], 10)),
        ),
        patch("internal.session.service._persist_after_invoke", fake_persist),
        patch(
            "internal.session.service._repark_graph_at_angle_gate",
            AsyncMock(),
        ) as repark,
    ):
        result = await choose_angle_turn(
            db, session, angle_index=0, image_format="comic_4panel"
        )

    repark.assert_awaited_once()
    assert result["interrupted"] is True
    first_update = graph.aupdate_state.await_args_list[0].args[1]
    assert first_update["chosen_image_format"] == "comic_4panel"
    for call in graph.aupdate_state.await_args_list:
        assert call.args[1].get("chosen_image_format") is not None


@pytest.mark.asyncio
async def test_stop_mid_choose_angle_restores_format_pick() -> None:
    """Stop mid-resume restores the card with the sticky format pick intact."""
    session = _angle_parked_session()
    session.state["chosen_image_format"] = "comic_4panel"
    db = AsyncMock()
    graph = SimpleNamespace(aupdate_state=AsyncMock())
    started = asyncio.Event()

    async def _slow_invoke(*_a, **_k):
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        return {}, False, None, None, [], 0

    with (
        patch(
            "internal.session.service.get_session_graph",
            return_value=graph,
        ),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch("internal.session.service._invoke_graph", side_effect=_slow_invoke),
        patch(
            "internal.session.service._restore_parked_after_resume_cancel",
            AsyncMock(),
        ) as restore,
        patch(
            "internal.session.service._adelete_graph_thread",
            AsyncMock(),
        ),
    ):
        pick_task = asyncio.create_task(
            choose_angle_turn(db, session, angle_index=0)
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)
        await stop_session_turn(db, session)
        with pytest.raises(asyncio.CancelledError):
            await pick_task

    restore.assert_awaited()
    assert restore.await_args.kwargs["kind"] == "angle"
    parked_state = restore.await_args.kwargs["parked_state"]
    assert parked_state["chosen_image_format"] == "comic_4panel"


@pytest.mark.asyncio
async def test_persist_after_invoke_keeps_image_format_in_state() -> None:
    """Hydrate: next_state must carry image_format + chosen_image_format."""
    from internal.session.service import _persist_after_invoke

    session = _session()
    db = AsyncMock()

    with patch(
        "internal.session.service.session_event_bus.publish_many",
        AsyncMock(),
    ):
        await _persist_after_invoke(
            db,
            session,
            user_msg=None,
            message_dicts=[],
            values={
                "messages": [],
                "image_format": "comic_4panel",
                "chosen_image_format": "comic_4panel",
            },
            still_interrupted=False,
            parked_node=None,
            progress_events=[],
            provider_error=None,
            user_content="",
            pre_state={},
            entry=None,
        )

    assert session.state["image_format"] == "comic_4panel"
    assert session.state["chosen_image_format"] == "comic_4panel"


@pytest.mark.asyncio
async def test_persist_emits_angle_pick_event_with_image_format() -> None:
    from internal.session.service import _persist_after_invoke

    session = _angle_parked_session()
    db = AsyncMock()
    published: list = []

    with patch(
        "internal.session.service.session_event_bus.publish_many",
        AsyncMock(side_effect=lambda _sid, evs: published.extend(evs)),
    ):
        await _persist_after_invoke(
            db,
            session,
            user_msg=None,
            message_dicts=[],
            values={
                "messages": [],
                "brief": session.state["brief"],
                "audience_catalog": session.state["audience_catalog"],
                "chosen_image_format": "comic_4panel",
            },
            still_interrupted=True,
            parked_node="angle_gate",
            progress_events=[],
            provider_error=None,
            user_content="",
            pre_state={},
            entry=None,
        )

    ev = next(e for e in published if e["type"] == "draft.awaiting_angle_pick")
    assert ev["data"]["image_format_options"] == ["single", "comic_4panel"]
    assert ev["data"]["recommended_image_format"] == "comic_4panel"
