import uuid
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.memory import repos
from internal.memory.database import get_db
from internal.memory.models import Session, User
from internal.session.events import format_sse, session_event_bus
from internal.session.service import run_session_turn
from schemas.session import (
    ConfirmSessionRequest,
    ConfirmSessionResponse,
    CreateSessionRequest,
    MessageResponse,
    PostMessageRequest,
    PostMessageResponse,
    SessionResponse,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _session_response(session: Session) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        company_id=session.company_id,
        user_id=session.user_id,
        mode=session.mode,
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _message_response(msg) -> MessageResponse:
    return MessageResponse(
        id=msg.id,
        session_id=msg.session_id,
        role=msg.role,
        content=msg.content,
        created_at=msg.created_at,
    )


async def _require_owned_session(
    db: AsyncSession, session_id: uuid.UUID, user: User
) -> Session:
    session = await repos.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return session


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionResponse:
    company = await repos.get_company(db, body.company_id)
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    if not await repos.user_has_org_access(db, user.id, body.company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    session = await repos.create_session(db, user_id=user.id, company_id=body.company_id)
    if body.initial_message:
        await run_session_turn(db, session, user_content=body.initial_message)
    await db.commit()
    await db.refresh(session)
    return _session_response(session)


@router.post("/{session_id}/messages", response_model=PostMessageResponse)
async def post_message(
    session_id: uuid.UUID,
    body: PostMessageRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostMessageResponse:
    session = await _require_owned_session(db, session_id, user)
    result = await run_session_turn(db, session, user_content=body.content)
    await db.commit()
    await db.refresh(session)

    all_msgs = await repos.list_session_messages(db, session.id)
    values = result["values"]
    return PostMessageResponse(
        session=_session_response(session),
        messages=[_message_response(m) for m in all_msgs],
        interrupted=result["interrupted"],
        mode=session.mode,
        revision=values.get("revision") or None,
        pending_confirm=bool(values.get("pending_confirm")),
        approval_token=values.get("approval_token"),
        events=result["events"],
    )


@router.get("/{session_id}/events")
async def session_events(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """SSE stream: initial snapshot, then live session events + heartbeats."""
    session = await _require_owned_session(db, session_id, user)
    draft = await repos.get_latest_preview_draft(db, session.id)
    snapshot_data = {
        "session_id": str(session.id),
        "mode": session.mode,
        "status": session.status,
        "state": session.state or {},
        "revision": draft.revision if draft else None,
        "approval_token": draft.approval_token if draft else None,
        "image_url": draft.image_url if draft else None,
    }

    async def event_stream() -> AsyncIterator[str]:
        yield format_sse("session.snapshot", snapshot_data)
        async for ev in session_event_bus.subscribe(session_id):
            yield format_sse(str(ev["type"]), ev.get("data") or {})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{session_id}/confirm", response_model=ConfirmSessionResponse)
async def confirm_session(
    session_id: uuid.UUID,
    body: ConfirmSessionRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConfirmSessionResponse:
    """Traditional Confirm handler — no LLM. Stub platform adapter writes tool_receipts."""
    session = await _require_owned_session(db, session_id, user)

    existing = await repos.get_tool_receipt_by_idempotency(db, body.idempotency_key)
    if existing:
        return ConfirmSessionResponse(
            receipt_id=existing.id,
            status=existing.status,
            tool_name=existing.tool_name,
            idempotency_key=existing.idempotency_key,
        )

    draft = await repos.get_preview_draft_by_token(db, session.id, body.approval_token)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid approval_token for session",
        )

    receipt = await repos.create_tool_receipt(
        db,
        session_id=session.id,
        user_id=user.id,
        tool_name="publish_social_post",
        idempotency_key=body.idempotency_key,
        status="stubbed",
        request={
            "platform": body.platform,
            "approval_token": body.approval_token,
            "revision": draft.revision,
        },
        response={"message": "Platform adapter stub — no publish performed"},
    )
    session.status = "confirmed"
    await db.commit()
    await session_event_bus.publish(
        session.id,
        "confirm.completed",
        {
            "receipt_id": str(receipt.id),
            "status": receipt.status,
            "idempotency_key": receipt.idempotency_key,
        },
    )
    return ConfirmSessionResponse(
        receipt_id=receipt.id,
        status=receipt.status,
        tool_name=receipt.tool_name,
        idempotency_key=receipt.idempotency_key,
    )
