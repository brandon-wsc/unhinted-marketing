import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.memory import repos
from internal.memory.database import get_db
from internal.memory.models import Session, User
from internal.session.events import format_sse, session_event_bus
from internal.session.service import (
    DEFAULT_PLATFORM,
    SessionTurnConflict,
    normalize_draft_copy,
    resume_image_turn,
    run_session_turn,
    stop_session_turn,
    update_session_draft,
)
from schemas.contracts import SessionBriefData
from schemas.session import (
    ConfirmSessionRequest,
    ConfirmSessionResponse,
    CreateSessionRequest,
    MessageResponse,
    PostMessageRequest,
    PostMessageResponse,
    ResumeImageResponse,
    SessionListItem,
    SessionListResponse,
    SessionMessagesResponse,
    SessionResponse,
    StopSessionResponse,
    UpdateDraftRequest,
    UpdateDraftResponse,
    UpdateSessionRequest,
)

logger = logging.getLogger(__name__)

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
        metadata=dict(msg.metadata_ or {}),
    )


def _brief_from_state(state: dict | None) -> SessionBriefData | None:
    raw = (state or {}).get("brief")
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        brief = SessionBriefData.model_validate(raw)
    except Exception:
        return None
    if not (brief.summary or brief.can_do or brief.cannot_do or brief.angles):
        return None
    return brief


async def _require_owned_session(
    db: AsyncSession, session_id: uuid.UUID, user: User
) -> Session:
    session = await repos.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return session


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    company_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 40,
) -> SessionListResponse:
    """List the current user's sessions (newest first), optionally by company."""
    if company_id is not None and not await repos.user_has_org_access(db, user.id, company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    rows = await repos.list_user_sessions(
        db, user_id=user.id, company_id=company_id, limit=limit
    )
    return SessionListResponse(
        sessions=[
            SessionListItem(
                id=session.id,
                company_id=session.company_id,
                user_id=session.user_id,
                mode=session.mode,
                status=session.status,
                created_at=session.created_at,
                updated_at=session.updated_at,
                title=_display_title(session, preview),
                pinned=bool(session.pinned),
            )
            for session, preview in rows
        ]
    )


def _display_title(session: Session, preview: str | None) -> str | None:
    if isinstance(session.title, str) and session.title.strip():
        return session.title.strip()[:120]
    if isinstance(preview, str) and preview.strip():
        return preview.strip()[:120]
    return None


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
        try:
            await run_session_turn(db, session, user_content=body.initial_message)
        except SessionTurnConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"reason": exc.reason, "message": exc.detail},
            ) from exc
    await db.commit()
    await db.refresh(session)
    return _session_response(session)


@router.patch("/{session_id}", response_model=SessionListItem)
async def update_session(
    session_id: uuid.UUID,
    body: UpdateSessionRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionListItem:
    """Rename and/or pin a session (Gemini-style history controls)."""
    session = await _require_owned_session(db, session_id, user)
    if body.title is None and not body.clear_title and body.pinned is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide title, clear_title, and/or pinned",
        )
    await repos.update_session_meta(
        db,
        session,
        title=body.title,
        clear_title=body.clear_title,
        pinned=body.pinned,
    )
    await db.commit()
    await db.refresh(session)
    msgs = await repos.list_session_messages(db, session.id)
    preview = next((m.content for m in msgs if m.role == "user"), None)
    return SessionListItem(
        id=session.id,
        company_id=session.company_id,
        user_id=session.user_id,
        mode=session.mode,
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
        title=_display_title(session, preview),
        pinned=bool(session.pinned),
    )


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    session = await _require_owned_session(db, session_id, user)
    await repos.delete_session(db, session)
    await db.commit()


@router.post("/{session_id}/messages", response_model=PostMessageResponse)
async def post_message(
    session_id: uuid.UUID,
    body: PostMessageRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostMessageResponse:
    session = await _require_owned_session(db, session_id, user)
    try:
        result = await run_session_turn(db, session, user_content=body.content)
    except SessionTurnConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": exc.reason, "message": exc.detail},
        ) from exc
    except asyncio.CancelledError:
        # Discard already committed inside run_session_turn.
        await db.rollback()
        raise
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


@router.post("/{session_id}/resume-image", response_model=ResumeImageResponse)
async def resume_image(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResumeImageResponse:
    """Resume parked interrupt_before executor_image_plan (ADR 0004)."""
    session = await _require_owned_session(db, session_id, user)
    try:
        result = await resume_image_turn(db, session)
    except SessionTurnConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": exc.reason, "message": exc.detail},
        ) from exc
    except asyncio.CancelledError:
        await db.rollback()
        raise
    await db.commit()
    await db.refresh(session)

    all_msgs = await repos.list_session_messages(db, session.id)
    values = result["values"]
    return ResumeImageResponse(
        session=_session_response(session),
        messages=[_message_response(m) for m in all_msgs],
        interrupted=result["interrupted"],
        mode=session.mode,
        revision=values.get("revision") or None,
        pending_confirm=bool(values.get("pending_confirm")),
        approval_token=values.get("approval_token"),
        events=result["events"],
    )


@router.post("/{session_id}/stop", response_model=StopSessionResponse)
async def stop_session(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StopSessionResponse:
    """Discard in-flight or parked turn (ADR 0004)."""
    session = await _require_owned_session(db, session_id, user)
    result = await stop_session_turn(db, session)
    await db.commit()
    return StopSessionResponse(
        status=result["status"],
        interrupted=bool(result.get("interrupted")),
        awaiting_image_ok=bool(result.get("awaiting_image_ok")),
    )


@router.get("/{session_id}/messages", response_model=SessionMessagesResponse)
async def get_session_messages(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionMessagesResponse:
    """Hydrate chat transcript for an owned session."""
    session = await _require_owned_session(db, session_id, user)
    msgs = await repos.list_session_messages(db, session.id)
    state = session.state or {}
    return SessionMessagesResponse(
        session=_session_response(session),
        messages=[_message_response(m) for m in msgs],
        brief=_brief_from_state(state),
        awaiting_image_ok=bool(state.get("awaiting_image_ok")),
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
    state = session.state or {}
    copy = normalize_draft_copy(
        (draft.copy if draft else None) or state.get("draft")
    )
    platform = (draft.platform if draft else None) or DEFAULT_PLATFORM

    interrupted = bool(state.get("awaiting_image_ok"))
    try:
        from internal.session.graph import get_session_graph

        graph = get_session_graph()
        snap = await graph.aget_state({"configurable": {"thread_id": str(session.id)}})
        interrupted = bool(snap.next)
    except Exception:
        # Graph/checkpointer may be unavailable in tests / early boot.
        logger.debug("session events: could not read graph interrupt state", exc_info=True)

    snapshot_data = {
        "session_id": str(session.id),
        "mode": session.mode,
        "status": session.status,
        "state": state,
        "revision": draft.revision if draft else state.get("revision"),
        "approval_token": draft.approval_token if draft else state.get("approval_token"),
        "image_url": draft.image_url if draft else state.get("image_url"),
        "copy": copy,
        "platform": platform,
        "interrupted": interrupted,
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


@router.post("/{session_id}/draft", response_model=UpdateDraftResponse)
async def update_draft(
    session_id: uuid.UUID,
    body: UpdateDraftRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UpdateDraftResponse:
    """Manual preview edit — no LLM. Bumps revision + approval_token."""
    session = await _require_owned_session(db, session_id, user)
    try:
        result = await update_session_draft(
            db,
            session,
            caption=body.caption,
            hashtags=body.hashtags,
            cta=body.cta,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    await db.commit()
    return UpdateDraftResponse(
        revision=int(result["revision"]),
        approval_token=str(result["approval_token"]),
        copy=result["copy"],
        image_url=result.get("image_url"),
        platform=str(result["platform"]),
        mode=str(result["mode"]),
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
        # User-private: never return another session/user's receipt (IDOR).
        if existing.session_id != session.id or existing.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key already used",
            )
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
