"""Graph-turn error handling must not lazy-load an expired Session row."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import InvalidRequestError

from internal.llm.resolve import CompanyLlmBundle
from internal.llm.router import LlmProviderError
from internal.session.service import (
    _invoke_graph,
    _llm_failure_reply,
    _turn_failure_reply,
    run_session_turn,
)
from internal.session.turn_registry import session_turn_registry


@pytest.fixture(autouse=True)
async def _clear_registry():
    session_turn_registry._entries.clear()
    yield
    session_turn_registry._entries.clear()


@pytest.fixture(autouse=True)
def _empty_byok_bundle():
    with patch(
        "internal.llm.resolve.load_company_llm_bundle",
        AsyncMock(return_value=CompanyLlmBundle()),
    ):
        yield


class _ExpiredAfterInvoke:
    """Stand-in for a Session whose attrs expire when the request transaction dies."""

    def __init__(self) -> None:
        self._id = uuid.uuid4()
        self._user_id = uuid.uuid4()
        self._company_id = uuid.uuid4()
        self.mode = "CHAT"
        self.state: dict = {}
        self.blocked = False

    def _get(self, value: uuid.UUID) -> uuid.UUID:
        if self.blocked:
            raise InvalidRequestError(
                "Can't operate on closed transaction inside context manager.  "
                "Please complete the context manager before emitting further commands."
            )
        return value

    @property
    def id(self) -> uuid.UUID:
        return self._get(self._id)

    @property
    def user_id(self) -> uuid.UUID:
        return self._get(self._user_id)

    @property
    def company_id(self) -> uuid.UUID:
        return self._get(self._company_id)


def _plain_session() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        mode="CHAT",
        status="active",
        state={},
    )


def test_turn_failure_reply_follows_user_script() -> None:
    assert "失敗" in _turn_failure_reply("幫我睇下市場")
    assert "failed" in _turn_failure_reply("look at the market").lower()


def test_llm_failure_reply_includes_kind() -> None:
    err = LlmProviderError("timed out", model="gpt-test", kind="timeout")
    zh = _llm_failure_reply("出帖", err)
    en = _llm_failure_reply("post this", err)
    assert "timeout" in zh and "gpt-test" in zh
    assert "timeout" in en and "gpt-test" in en


@pytest.mark.asyncio
async def test_invoke_graph_node_error_does_not_touch_expired_session() -> None:
    session = _ExpiredAfterInvoke()
    db = AsyncMock()

    async def boom_ainvoke(*_a, **_k):
        session.blocked = True
        raise InvalidRequestError(
            "Can't operate on closed transaction inside context manager."
        )

    graph = SimpleNamespace(ainvoke=boom_ainvoke, aget_state=AsyncMock())

    with patch("internal.session.service.get_session_graph", return_value=graph):
        (
            values,
            interrupted,
            parked_node,
            provider_error,
            events,
            _duration,
        ) = await _invoke_graph(
            db,
            session,  # type: ignore[arg-type]
            graph_input={},
            user_content="幫我睇下市場",
            message_dicts=[{"role": "user", "content": "幫我睇下市場"}],
        )

    assert parked_node is None

    assert interrupted is False
    assert provider_error is None
    assert values["error"] == _turn_failure_reply("幫我睇下市場")
    assert values["messages"][-1]["role"] == "assistant"
    assert "失敗" in values["messages"][-1]["content"]
    db.rollback.assert_awaited()
    graph.aget_state.assert_not_awaited()
    assert events == []


@pytest.mark.asyncio
async def test_invoke_graph_llm_error_still_surfaces_provider_copy() -> None:
    session = _ExpiredAfterInvoke()
    db = AsyncMock()
    err = LlmProviderError("nope", model="m", kind="auth")

    async def boom_ainvoke(*_a, **_k):
        session.blocked = True
        raise err

    graph = SimpleNamespace(
        ainvoke=boom_ainvoke,
        aget_state=AsyncMock(
            side_effect=InvalidRequestError("closed transaction"),
        ),
    )

    with patch("internal.session.service.get_session_graph", return_value=graph):
        (
            values,
            interrupted,
            parked_node,
            provider_error,
            _events,
            _duration,
        ) = await _invoke_graph(
            db,
            session,  # type: ignore[arg-type]
            graph_input={},
            user_content="hello",
            message_dicts=[{"role": "user", "content": "hello"}],
        )

    assert interrupted is False
    assert parked_node is None
    assert provider_error is err
    assert "AI service unavailable" in values["messages"][-1]["content"]
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_session_turn_graph_error_persists_and_clears_registry() -> None:
    session = _plain_session()
    db = AsyncMock()
    user_msg = SimpleNamespace(id=uuid.uuid4(), metadata_={})

    async def boom_ainvoke(*_a, **_k):
        raise RuntimeError("research_ingest exploded")

    graph = SimpleNamespace(ainvoke=boom_ainvoke, aget_state=AsyncMock())

    with (
        patch(
            "internal.session.service.session_park_kind",
            AsyncMock(return_value=None),
        ),
        patch(
            "internal.session.service.repos.add_session_message",
            AsyncMock(return_value=user_msg),
        ),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch("internal.session.service.get_session_graph", return_value=graph),
        patch(
            "internal.session.service._persist_after_invoke",
            AsyncMock(return_value={"ok": True}),
        ) as persist,
    ):
        result = await run_session_turn(db, session, user_content="hi")

    assert result == {"ok": True}
    persist.assert_awaited()
    assert persist.await_args.kwargs["provider_error"] is None
    assert "failed" in persist.await_args.kwargs["values"]["error"].lower()
    assert session_turn_registry.get(session.id) is None
    assert session_turn_registry.is_busy(session.id) is False


@pytest.mark.asyncio
async def test_run_session_turn_clears_registry_when_session_id_expires() -> None:
    session = _ExpiredAfterInvoke()
    db = AsyncMock()
    user_msg = SimpleNamespace(id=uuid.uuid4(), metadata_={})
    captured_id = session.id

    async def boom_invoke(*_a, **_k):
        session.blocked = True
        raise RuntimeError("persist path never reached")

    with (
        patch(
            "internal.session.service.session_park_kind",
            AsyncMock(return_value=None),
        ),
        patch(
            "internal.session.service.repos.add_session_message",
            AsyncMock(return_value=user_msg),
        ),
        patch(
            "internal.session.service.repos.list_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch("internal.session.service._invoke_graph", boom_invoke),
        pytest.raises(RuntimeError, match="persist path never reached"),
    ):
        await run_session_turn(db, session, user_content="hi")

    assert session_turn_registry.get(captured_id) is None
    assert session_turn_registry.is_busy(captured_id) is False
