import asyncio
import logging
import re
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.media.storage import MediaStorageError
from internal.memory import repos
from internal.memory.database import get_db
from internal.memory.models import Session, User
from internal.session.events import format_sse, session_event_bus
from internal.session.graph import INTERRUPT_BEFORE
from internal.session.service import (
    DEFAULT_PLATFORM,
    SessionTurnConflict,
    add_session_image,
    copy_session_preview,
    list_latest_session_media,
    normalize_draft_copy,
    regen_session_image,
    remove_session_image,
    resume_image_turn,
    run_session_turn,
    stop_session_turn,
    update_session_draft,
    update_session_image_plan,
    upload_session_image,
)
from internal.tools.publish import (
    PUBLISHED_STATUS,
    STUB_STATUS,
    PublishPreconditionError,
    publish_social_post,
)
from schemas.contracts import DraftCopy, PreviewMediaItem, SessionBriefData
from schemas.session import (
    AddSessionImageRequest,
    ConfirmSessionRequest,
    ConfirmSessionResponse,
    CreateSessionRequest,
    ForkOrigin,
    ForkPreviewNote,
    ForkRef,
    ForkSessionRequest,
    ForkSessionResponse,
    MessageResponse,
    PostMessageRequest,
    PostMessageResponse,
    PreviewMediaMutationResponse,
    ResumeImageRequest,
    ResumeImageResponse,
    SessionListItem,
    SessionListResponse,
    SessionMediaListResponse,
    SessionMessagesResponse,
    SessionResponse,
    StopSessionResponse,
    UpdateDraftRequest,
    UpdateDraftResponse,
    UpdateImagePlanRequest,
    UpdateSessionRequest,
)
from schemas.tools import PublishSocialPostRequest

logger = logging.getLogger(__name__)

_CONFIRM_SUCCESS = frozenset({STUB_STATUS, PUBLISHED_STATUS})

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


def _image_interrupt_from_snapshot(state: dict | None, snap_next: object) -> bool:
    """Generate-image CTA only — a running graph (`snap.next` non-empty) is not parked."""
    if bool((state or {}).get("awaiting_image_ok")):
        return True
    nxt = snap_next if isinstance(snap_next, (list, tuple)) else ()
    return any(node in nxt for node in INTERRUPT_BEFORE)


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
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> SessionListResponse:
    """List the current user's sessions (newest first), optionally by company.

    With ``q``, searches session titles and message content across all of the
    user's history (flat newest-first) and includes a matched snippet.
    """
    if company_id is not None and not await repos.user_has_org_access(db, user.id, company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    query = (q or "").strip()
    if query:
        rows = await repos.search_user_sessions(
            db, user_id=user.id, company_id=company_id, q=query, limit=limit
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
                    matched_snippet=_search_snippet(
                        query,
                        match_content,
                        _brief_text(session.state),
                        _draft_text((session.state or {}).get("draft")),
                        _draft_text(draft_copy),
                    ),
                )
                for session, preview, match_content, draft_copy in rows
            ]
        )
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


def _matched_snippet(content: str, query: str, width: int = 120) -> str:
    """Context window around the first case-insensitive match in content."""
    text = " ".join(content.split())
    idx = text.lower().find(query.lower())
    if idx < 0:
        return text[:width]
    start = max(0, idx - (width - len(query)) // 2)
    end = min(len(text), start + width)
    start = max(0, end - width)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet += "…"
    return snippet


def _search_snippet(query: str, *candidates: str | None) -> str | None:
    """First candidate that actually contains the query, windowed."""
    for text in candidates:
        if text and query.lower() in " ".join(text.split()).lower():
            return _matched_snippet(text, query)
    return None


def _brief_text(state: dict | None) -> str | None:
    brief = _brief_from_state(state)
    if not brief:
        return None
    parts = [brief.summary, *brief.can_do, *brief.cannot_do, *brief.angles]
    if brief.persona:
        parts.append(brief.persona)
    return " ".join(p for p in parts if p) or None


def _draft_text(copy: dict | None) -> str | None:
    if not isinstance(copy, dict):
        return None
    parts: list[str] = []
    caption = copy.get("caption")
    hashtags = copy.get("hashtags")
    cta = copy.get("cta")
    if isinstance(caption, str):
        parts.append(caption)
    if isinstance(hashtags, list):
        parts.extend(h for h in hashtags if isinstance(h, str))
    if isinstance(cta, str):
        parts.append(cta)
    return " ".join(parts) or None


def _display_title(session: Session, preview: str | None) -> str | None:
    if isinstance(session.title, str) and session.title.strip():
        return session.title.strip()[:120]
    if isinstance(preview, str) and preview.strip():
        return preview.strip()[:120]
    return None


_FORK_TITLE_PREFIX = re.compile(r"^\(\d+\)\s*")


async def _fork_origin(db: AsyncSession, session: Session) -> ForkOrigin | None:
    """Live source title when the source session survives; snapshot otherwise (ADR 0017)."""
    if session.forked_from_message_id is None:
        return None
    title = session.forked_from_title
    if session.forked_from_session_id is not None:
        source = await repos.get_session(db, session.forked_from_session_id)
        if source is not None:
            src_msgs = await repos.list_session_messages(db, source.id)
            preview = next((m.content for m in src_msgs if m.role == "user"), None)
            title = _display_title(source, preview) or title
    return ForkOrigin(
        session_id=session.forked_from_session_id,
        message_id=session.forked_from_message_id,
        title=title,
    )


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
        result = await run_session_turn(
            db,
            session,
            user_content=body.content,
            source_question_id=body.source_question_id,
        )
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
    body: Annotated[ResumeImageRequest, Body()] = ResumeImageRequest(),
) -> ResumeImageResponse:
    """Resume parked interrupt_before executor_image_plan (ADR 0004)."""
    session = await _require_owned_session(db, session_id, user)
    try:
        result = await resume_image_turn(
            db,
            session,
            image_format=body.image_format,
        )
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


@router.post("/{session_id}/fork", response_model=ForkSessionResponse, status_code=201)
async def fork_session(
    session_id: uuid.UUID,
    body: ForkSessionRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ForkSessionResponse:
    """Branch this chat at a message into a new session (ADR 0017).

    Copies the transcript up to and including the fork message plus the preview
    draft/media as it existed at that message (time-aligned, fresh
    approval_token). Lineage is recorded on the new session; the fork-point
    copy carries ``metadata.fork_point`` so the client can place the divider.
    ``preview_note`` flags the surprising cases so the client can toast.
    """
    session = await _require_owned_session(db, session_id, user)
    msgs = await repos.list_session_messages(db, session.id)
    fork_idx = next((i for i, m in enumerate(msgs) if m.id == body.message_id), None)
    if fork_idx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    copied = msgs[: fork_idx + 1]

    first_user = next((m.content for m in msgs if m.role == "user"), None)
    display = _display_title(session, first_user)
    base = _FORK_TITLE_PREFIX.sub("", display or "").strip()
    n = await repos.count_session_forks(db, session.id) + 1
    title = f"({n}) {base}"[:200] if base else None

    fork = await repos.create_session(db, user_id=user.id, company_id=session.company_id)
    fork.title = title
    fork.forked_from_session_id = session.id
    fork.forked_from_message_id = body.message_id
    fork.forked_from_title = display

    for i, m in enumerate(copied):
        meta = dict(m.metadata_ or {})
        if i == fork_idx:
            meta["fork_point"] = True
        await repos.add_session_message(
            db,
            session_id=fork.id,
            role=m.role,
            content=m.content,
            metadata=meta,
            created_at=m.created_at,
        )

    fork_msg = msgs[fork_idx]
    preview = await copy_session_preview(db, session, fork, as_of=fork_msg.created_at)
    await db.commit()
    await db.refresh(fork)

    preview_note: ForkPreviewNote | None = None
    if preview.copied and preview.latest_revision != preview.copied_revision:
        preview_note = "carried_stale"
    elif not preview.copied and preview.latest_revision is not None:
        preview_note = "not_carried_later"

    new_msgs = await repos.list_session_messages(db, fork.id)
    return ForkSessionResponse(
        session=_session_response(fork),
        messages=[_message_response(m) for m in new_msgs],
        forked_from=ForkOrigin(
            session_id=session.id,
            message_id=body.message_id,
            title=display,
        ),
        preview_note=preview_note,
    )


@router.get("/{session_id}/messages", response_model=SessionMessagesResponse)
async def get_session_messages(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionMessagesResponse:
    """Hydrate chat transcript for an owned session (with fork lineage, ADR 0017)."""
    session = await _require_owned_session(db, session_id, user)
    msgs = await repos.list_session_messages(db, session.id)
    state = session.state or {}

    forks = await repos.list_forks_for_messages(db, [m.id for m in msgs])
    forks_by_message: dict[uuid.UUID, list[Session]] = {}
    for f in forks:
        if f.forked_from_message_id is not None:
            forks_by_message.setdefault(f.forked_from_message_id, []).append(f)
    messages: list[MessageResponse] = []
    for m in msgs:
        resp = _message_response(m)
        resp.forks = [
            ForkRef(session_id=f.id, title=f.title, created_at=f.created_at)
            for f in forks_by_message.get(m.id, [])
        ]
        messages.append(resp)

    return SessionMessagesResponse(
        session=_session_response(session),
        messages=messages,
        brief=_brief_from_state(state),
        awaiting_image_ok=bool(state.get("awaiting_image_ok")),
        forked_from=await _fork_origin(db, session),
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
    media_items = await list_latest_session_media(db, session)

    interrupted = _image_interrupt_from_snapshot(state, ())
    try:
        from internal.session.graph import get_session_graph

        graph = get_session_graph()
        snap = await graph.aget_state({"configurable": {"thread_id": str(session.id)}})
        interrupted = _image_interrupt_from_snapshot(state, snap.next)
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
        "media": media_items,
        "copy": copy,
        "platform": platform,
        "interrupted": interrupted,
    }
    receipt_row = await repos.get_latest_publish_receipt(db, session.id)
    if receipt_row:
        snapshot_data["confirm_receipt"] = _confirm_response(receipt_row).model_dump(mode="json")

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
        media=[PreviewMediaItem.model_validate(m) for m in (result.get("media") or [])],
        platform=str(result["platform"]),
        mode=str(result["mode"]),
    )


def _media_mutation_response(result: dict) -> PreviewMediaMutationResponse:
    return PreviewMediaMutationResponse(
        revision=int(result["revision"]),
        approval_token=str(result["approval_token"]),
        copy=result["copy"],
        image_url=result.get("image_url"),
        media=[PreviewMediaItem.model_validate(m) for m in (result.get("media") or [])],
        platform=str(result["platform"]),
        mode=str(result["mode"]),
    )


@router.get("/{session_id}/media", response_model=SessionMediaListResponse)
async def get_session_media(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionMediaListResponse:
    """List media for the latest preview draft (ADR 0008)."""
    session = await _require_owned_session(db, session_id, user)
    items = await list_latest_session_media(db, session)
    return SessionMediaListResponse(
        media=[PreviewMediaItem.model_validate(m) for m in items]
    )


@router.patch(
    "/{session_id}/media/{image_id}/plan",
    response_model=PreviewMediaMutationResponse,
)
async def patch_session_image_plan(
    session_id: uuid.UUID,
    image_id: uuid.UUID,
    body: UpdateImagePlanRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PreviewMediaMutationResponse:
    """Edit image plan → new image row + new draft (no LLM)."""
    session = await _require_owned_session(db, session_id, user)
    try:
        result = await update_session_image_plan(
            db, session, image_id=image_id, plan=dict(body.plan or {})
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    await db.commit()
    return _media_mutation_response(result)


@router.post(
    "/{session_id}/media/{image_id}/regen",
    response_model=PreviewMediaMutationResponse,
)
async def post_session_image_regen(
    session_id: uuid.UUID,
    image_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PreviewMediaMutationResponse:
    """Regenerate image from plan → new image row + new draft."""
    from internal.llm.router import LlmProviderError

    session = await _require_owned_session(db, session_id, user)
    try:
        result = await regen_session_image(db, session, image_id=image_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except LlmProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"reason": "llm_error", "message": str(exc)},
        ) from exc
    await db.commit()
    return _media_mutation_response(result)


@router.post("/{session_id}/media", response_model=PreviewMediaMutationResponse)
async def post_session_media(
    session_id: uuid.UUID,
    body: AddSessionImageRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PreviewMediaMutationResponse:
    """Add a pending image slot → new image row + new draft."""
    session = await _require_owned_session(db, session_id, user)
    try:
        result = await add_session_image(
            db,
            session,
            format=str(body.format or "single"),
            plan=body.plan,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    await db.commit()
    return _media_mutation_response(result)


@router.post(
    "/{session_id}/media/{image_id}/remove",
    response_model=PreviewMediaMutationResponse,
)
async def post_session_image_remove(
    session_id: uuid.UUID,
    image_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PreviewMediaMutationResponse:
    """Remove image from current draft media_ids → new draft (orphan row OK)."""
    session = await _require_owned_session(db, session_id, user)
    try:
        result = await remove_session_image(db, session, image_id=image_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    await db.commit()
    return _media_mutation_response(result)


@router.post(
    "/{session_id}/media/{image_id}/upload",
    response_model=PreviewMediaMutationResponse,
)
async def post_session_image_upload(
    session_id: uuid.UUID,
    image_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File(...)],
) -> PreviewMediaMutationResponse:
    """Upload image bytes → new preview_images row + replace slot in draft."""
    session = await _require_owned_session(db, session_id, user)
    raw = await file.read()
    content_type = file.content_type or "application/octet-stream"
    try:
        result = await upload_session_image(
            db,
            session,
            image_id=image_id,
            data=raw,
            content_type=content_type,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except MediaStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    await db.commit()
    return _media_mutation_response(result)


def _draft_has_image(draft) -> bool:
    if list(draft.media_ids or []):
        return True
    return bool((draft.image_url or "").strip())


async def _publish_image_url(db: AsyncSession, draft) -> str | None:
    ids = list(draft.media_ids or [])
    if ids:
        images = await repos.get_preview_images_by_ids(db, [ids[0]])
        if images:
            url = (images[0].url or "").strip()
            if url:
                return url
    url = (draft.image_url or "").strip()
    return url or None


def _optional_str(payload: dict, key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _confirm_response(receipt) -> ConfirmSessionResponse:
    payload = receipt.response if isinstance(receipt.response, dict) else {}
    return ConfirmSessionResponse(
        receipt_id=receipt.id,
        status=receipt.status,
        tool_name=receipt.tool_name,
        idempotency_key=receipt.idempotency_key,
        permalink=_optional_str(payload, "permalink"),
        error_kind=_optional_str(payload, "error_kind"),
    )


@router.post("/{session_id}/confirm", response_model=ConfirmSessionResponse)
async def confirm_session(
    session_id: uuid.UUID,
    body: ConfirmSessionRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConfirmSessionResponse:
    """Traditional Confirm handler — no LLM. Adapter writes tool_receipts (ADR 0003 / 0022)."""
    session = await _require_owned_session(db, session_id, user)

    existing = await repos.get_tool_receipt_by_idempotency(db, body.idempotency_key)
    if existing:
        # User-private: never return another session/user's receipt (IDOR).
        if existing.session_id != session.id or existing.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key already used",
            )
        return _confirm_response(existing)

    draft = await repos.get_preview_draft_by_token(db, session.id, body.approval_token)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid approval_token for session",
        )
    if not _draft_has_image(draft):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="image_required",
        )

    image_url = await _publish_image_url(db, draft)
    req = PublishSocialPostRequest(
        session_id=session.id,
        approval_token=body.approval_token,
        idempotency_key=body.idempotency_key,
        platform=body.platform,
        draft_copy=DraftCopy.model_validate(normalize_draft_copy(draft.copy)),
        image_url=image_url,
        revision=draft.revision,
    )
    try:
        outcome = await publish_social_post(db, req, company_id=session.company_id)
    except PublishPreconditionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.detail,
        ) from exc

    receipt = await repos.create_tool_receipt(
        db,
        session_id=session.id,
        user_id=user.id,
        tool_name="publish_social_post",
        idempotency_key=body.idempotency_key,
        status=outcome.status,
        request={
            "platform": body.platform,
            "approval_token": body.approval_token,
            "revision": draft.revision,
        },
        response={
            "message": outcome.message,
            "platform": outcome.platform,
            "permalink": outcome.permalink,
            "error_kind": outcome.error_kind,
            "media_id": outcome.media_id,
        },
    )
    if outcome.status in _CONFIRM_SUCCESS:
        session.status = "confirmed"
    await db.commit()
    await session_event_bus.publish(
        session.id,
        "confirm.completed",
        {
            "receipt_id": str(receipt.id),
            "status": receipt.status,
            "tool_name": receipt.tool_name,
            "idempotency_key": receipt.idempotency_key,
            "permalink": outcome.permalink,
            "error_kind": outcome.error_kind,
        },
    )
    return _confirm_response(receipt)
