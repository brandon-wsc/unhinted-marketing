import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from schemas.session import (
    ConfirmSessionRequest,
    ConfirmSessionResponse,
    CreateSessionRequest,
    MessageResponse,
    PostMessageRequest,
    PostMessageResponse,
    SessionEvent,
    SessionListItem,
    SessionListResponse,
    SessionMessagesResponse,
    SessionResponse,
    UpdateDraftRequest,
    UpdateDraftResponse,
    UpdateSessionRequest,
)


def _now() -> datetime:
    return datetime.now(UTC)


def test_create_session_request() -> None:
    body = CreateSessionRequest(company_id=uuid.uuid4())
    assert body.initial_message is None


def test_create_session_rejects_long_message() -> None:
    with pytest.raises(ValidationError):
        CreateSessionRequest(company_id=uuid.uuid4(), initial_message="x" * 8001)


def test_session_response_models() -> None:
    sid = uuid.uuid4()
    cid = uuid.uuid4()
    uid = uuid.uuid4()
    now = _now()
    session = SessionResponse(
        id=sid,
        company_id=cid,
        user_id=uid,
        mode="CHAT",
        status="active",
        created_at=now,
        updated_at=now,
    )
    item = SessionListItem(
        id=sid,
        company_id=cid,
        user_id=uid,
        mode="CHAT",
        status="active",
        created_at=now,
        updated_at=now,
        title="Hello",
        pinned=True,
    )
    listed = SessionListResponse(sessions=[item])
    assert listed.sessions[0].title == "Hello"
    assert session.id == sid


def test_update_session_request_defaults() -> None:
    body = UpdateSessionRequest()
    assert body.title is None
    assert body.pinned is None
    assert body.clear_title is False


def test_post_message_requires_content() -> None:
    with pytest.raises(ValidationError):
        PostMessageRequest(content="")


def test_message_and_post_response() -> None:
    now = _now()
    sid = uuid.uuid4()
    session = SessionResponse(
        id=sid,
        company_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        mode="CHAT",
        status="active",
        created_at=now,
        updated_at=now,
    )
    msg = MessageResponse(
        id=uuid.uuid4(),
        session_id=sid,
        role="user",
        content="hi",
        created_at=now,
    )
    assert msg.metadata == {}
    hydrated = SessionMessagesResponse(session=session, messages=[msg])
    assert len(hydrated.messages) == 1
    posted = PostMessageResponse(session=session, messages=[msg], mode="CHAT")
    assert posted.interrupted is False
    assert posted.events == []


def test_confirm_session_request_validation() -> None:
    with pytest.raises(ValidationError):
        ConfirmSessionRequest(approval_token="short", idempotency_key="also-short")
    ok = ConfirmSessionRequest(
        approval_token="token-ok-12",
        idempotency_key="idem-key-12",
    )
    assert ok.platform == "stub"


def test_confirm_and_draft_responses() -> None:
    receipt = ConfirmSessionResponse(
        receipt_id=uuid.uuid4(),
        status="stubbed",
        tool_name="publish_social_post",
        idempotency_key="idem-1",
    )
    assert receipt.status == "stubbed"
    draft = UpdateDraftResponse(
        revision=2,
        approval_token="new-token",
        copy={"caption": "c", "hashtags": [], "cta": ""},
        platform="instagram",
        mode="PREVIEW",
    )
    assert draft.image_url is None
    req = UpdateDraftRequest(caption="Hello", hashtags=["hk"])
    assert req.cta == ""


def test_session_event() -> None:
    ev = SessionEvent(type="session.snapshot")
    assert ev.data == {}
