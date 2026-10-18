import asyncio
import logging
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import bearer_scheme, get_current_user, resolve_current_user
from internal.auth.org import member_publish_requires_approval
from internal.media.gc import collect_session_store_keys, reclaim_unreferenced_keys
from internal.media.storage import (
    MediaStorageError,
    delete_key,
    put_bytes,
    resolve_stored_url,
    stored_ref_is_image,
)
from internal.memory import repos
from internal.memory.database import get_db, open_session
from internal.memory.models import (
    Attachment,
    AttachmentSession,
    Session,
    SessionMessage,
    User,
)
from internal.session.events import format_sse, session_event_bus
from internal.session.graph import ANGLE_GATE_NODE, IMAGE_PARK_NODE
from internal.session.nodes import angle_pick_payload, recommended_image_format
from internal.session.service import (
    DEFAULT_PLATFORM,
    SessionTurnConflict,
    add_session_image,
    choose_angle_turn,
    copy_session_preview,
    list_latest_session_media,
    normalize_draft_copy,
    regen_session_image,
    remove_session_image,
    resolve_source_signals,
    resume_image_turn,
    run_session_turn,
    stop_session_turn,
    update_session_draft,
    update_session_image_plan,
    upload_session_image,
)
from internal.tools.publish import (
    PublishPreconditionError,
    execute_publish,
    resolve_publish_image_url,
)
from schemas.company import UsageLimitExceededDetail
from schemas.contracts import (
    DraftCopy,
    PreviewMediaItem,
    PreviewUpdatedData,
    SessionBriefData,
    SourceSignal,
)
from schemas.session import (
    AddSessionImageRequest,
    AttachmentDigest,
    AttachmentListResponse,
    AttachmentOut,
    ChooseAngleRequest,
    ChooseAngleResponse,
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
    StopSessionRequest,
    StopSessionResponse,
    UpdateDraftRequest,
    UpdateDraftResponse,
    UpdateImagePlanRequest,
    UpdateSessionRequest,
)
from schemas.tools import PublishSocialPostRequest

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


def _message_response(msg, attachments: list[AttachmentDigest] | None = None) -> MessageResponse:
    return MessageResponse(
        id=msg.id,
        session_id=msg.session_id,
        role=msg.role,
        content=msg.content,
        created_at=msg.created_at,
        metadata=dict(msg.metadata_ or {}),
        attachments=attachments or [],
    )


def _attachment_ids_of(msg: SessionMessage) -> list[uuid.UUID]:
    """Uuids stored in ``metadata.attachment_ids`` — bad entries dropped."""
    ids: list[uuid.UUID] = []
    for raw in (msg.metadata_ or {}).get("attachment_ids") or []:
        try:
            ids.append(uuid.UUID(str(raw)))
        except (ValueError, TypeError, AttributeError):
            continue
    return ids


async def _message_attachment_map(
    db: AsyncSession, msgs: list[SessionMessage]
) -> dict[uuid.UUID, list[AttachmentDigest]]:
    """Digest chips for messages carrying ``metadata.attachment_ids``.

    ADR 0047 §5 — one batched lookup; ids that no longer resolve are dropped
    so the transcript never fails on a GC'd attachment.
    """
    wanted: dict[uuid.UUID, list[uuid.UUID]] = {}
    all_ids: set[uuid.UUID] = set()
    for m in msgs:
        ids = _attachment_ids_of(m)
        if ids:
            wanted[m.id] = ids
            all_ids.update(ids)
    if not all_ids:
        return {}
    rows = await db.scalars(select(Attachment).where(Attachment.id.in_(all_ids)))
    by_id = {r.id: r for r in rows}
    return {
        mid: [
            AttachmentDigest(
                id=by_id[aid].id,
                filename=by_id[aid].filename,
                status=by_id[aid].status,
                title=(by_id[aid].doc_profile or {}).get("title"),
            )
            for aid in ids
            if aid in by_id
        ]
        for mid, ids in wanted.items()
    }


async def _messages_response(db: AsyncSession, msgs: list[SessionMessage]) -> list[MessageResponse]:
    """Transcript rows with batched attachment chips (ADR 0047 §5)."""
    chips = await _message_attachment_map(db, msgs)
    return [_message_response(m, attachments=chips.get(m.id)) for m in msgs]


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


def _parked_node_from_snapshot(state: dict | None, snap_next: object) -> str | None:
    """Which interrupt node the graph waits on — flags first, then snap.next."""
    if bool((state or {}).get("awaiting_image_ok")):
        return IMAGE_PARK_NODE
    if bool((state or {}).get("awaiting_angle_pick")):
        return ANGLE_GATE_NODE
    nxt = snap_next if isinstance(snap_next, (list, tuple)) else ()
    for node in (ANGLE_GATE_NODE, IMAGE_PARK_NODE):
        if node in nxt:
            return node
    return None


async def _require_owned_session(db: AsyncSession, session_id: uuid.UUID, user: User) -> Session:
    session = await repos.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return session


async def _enforce_member_token_limit(db: AsyncSession, session: Session, user: User) -> None:
    """ADR 0041: cap org `member` token spend at the turn boundary.

    Owner/admin bypass the cap entirely. The cap counts the member's whole
    spend — platform key ('env') and org BYOK ('org') are both the org's
    bill. llm_call_records flush asynchronously after each call, so
    in-flight turns can overshoot slightly — an accepted guardrail lag, not
    a hard rate limiter.
    """
    membership = await repos.get_org_membership(db, user.id, session.company_id)
    if membership is None or membership.role != "member" or membership.monthly_token_limit is None:
        return
    period_start, period_end = repos.member_month_bounds()
    by_source = await repos.sum_member_tokens_by_source(
        db, user_id=user.id, company_id=session.company_id, since=period_start
    )
    used = sum(by_source.values())
    if used >= membership.monthly_token_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=UsageLimitExceededDetail(
                limit=membership.monthly_token_limit,
                used=used,
                period_end=period_end,
            ).model_dump(mode="json"),
        )


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
    rows = await repos.list_user_sessions(db, user_id=user.id, company_id=company_id, limit=limit)
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
        await _enforce_member_token_limit(db, session, user)
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
    keys: list[str] | None
    try:
        keys = await collect_session_store_keys(db, session.id)
    except Exception:
        logger.warning("media GC collect failed session=%s", session_id, exc_info=True)
        keys = None
    # ADR 0047 §13 — scratch attachments die with their last referencing
    # session; shared/saved rows are detached before the FK cascade runs.
    attachment_keys = await repos.release_session_attachments(db, session.id)
    await repos.delete_session(db, session)
    await db.commit()
    if keys:
        await reclaim_unreferenced_keys(db, keys)
    for key in attachment_keys:
        try:
            await delete_key(key)
        except Exception:
            logger.warning("attachment GC failed for key=%s", key, exc_info=True)


async def _message_attachment_reachable(
    db: AsyncSession,
    attachment: Attachment | None,
    *,
    session: Session,
    user: User,
) -> bool:
    """ADR 0047 §3/§14 owner matrix for ``PostMessageRequest.attachment_ids``.

    Reachable = this session's scratch (``attachment_sessions`` join row, or
    ``session_id`` + uploader match) or the member's library row
    (``owner_scope='user'`` + ``user_id`` match, ``owner_scope='org'`` in the
    same company). Everything else refuses identically — unknown, cross-tenant
    and other-session scratch ids all map to the same 404 so existence never
    leaks.
    """
    if attachment is None or attachment.company_id != session.company_id:
        return False
    if attachment.owner_scope == "org":
        return True
    if attachment.owner_scope == "user":
        return attachment.user_id == user.id
    if attachment.owner_scope == "session":
        if attachment.session_id == session.id and attachment.user_id == user.id:
            return True
        return await db.get(AttachmentSession, (attachment.id, session.id)) is not None
    return False


async def _resolve_message_attachments(
    db: AsyncSession,
    session: Session,
    user: User,
    attachment_ids: list[uuid.UUID],
) -> None:
    """Validate every ``attachment_ids`` entry before the turn runs — one bad
    id fails the whole message with a uniform 404."""
    unique_ids = list(dict.fromkeys(attachment_ids))
    if not unique_ids:
        return
    rows = await db.scalars(select(Attachment).where(Attachment.id.in_(unique_ids)))
    by_id = {r.id: r for r in rows}
    for attachment_id in unique_ids:
        if not await _message_attachment_reachable(
            db, by_id.get(attachment_id), session=session, user=user
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found"
            )


@router.post("/{session_id}/messages", response_model=PostMessageResponse)
async def post_message(
    session_id: uuid.UUID,
    body: PostMessageRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostMessageResponse:
    session = await _require_owned_session(db, session_id, user)
    await _resolve_message_attachments(db, session, user, body.attachment_ids)
    await _enforce_member_token_limit(db, session, user)
    try:
        result = await run_session_turn(
            db,
            session,
            user_content=body.content,
            source_question_id=body.source_question_id,
            attachment_ids=body.attachment_ids,
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
        messages=await _messages_response(db, all_msgs),
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
    """Resume parked interrupt_before executor_image_gen (ADR 0004 / 0036)."""
    session = await _require_owned_session(db, session_id, user)
    await _enforce_member_token_limit(db, session, user)
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
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
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
        messages=await _messages_response(db, all_msgs),
        interrupted=result["interrupted"],
        mode=session.mode,
        revision=values.get("revision") or None,
        pending_confirm=bool(values.get("pending_confirm")),
        approval_token=values.get("approval_token"),
        events=result["events"],
    )


@router.post("/{session_id}/choose-angle", response_model=ChooseAngleResponse)
async def choose_angle(
    session_id: uuid.UUID,
    body: ChooseAngleRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ChooseAngleResponse:
    """Pick a brainstormed angle — resume parked interrupt_before angle_gate (ADR 0029)."""
    session = await _require_owned_session(db, session_id, user)
    await _enforce_member_token_limit(db, session, user)
    if body.angle_index is None and not (body.angle or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide angle_index or angle",
        )
    try:
        result = await choose_angle_turn(
            db,
            session,
            angle_index=body.angle_index,
            angle_text=body.angle,
            persona=body.persona,
            image_format=body.image_format,
        )
    except SessionTurnConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": exc.reason, "message": exc.detail},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except asyncio.CancelledError:
        await db.rollback()
        raise
    await db.commit()
    await db.refresh(session)

    all_msgs = await repos.list_session_messages(db, session.id)
    values = result["values"]
    return ChooseAngleResponse(
        session=_session_response(session),
        messages=await _messages_response(db, all_msgs),
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
    body: Annotated[StopSessionRequest, Body()] = StopSessionRequest(),
) -> StopSessionResponse:
    """Discard in-flight/parked turn, or keep it on interrupt (ADR 0004 / 0035)."""
    session = await _require_owned_session(db, session_id, user)
    result = await stop_session_turn(db, session, mode=body.mode)
    await db.commit()
    raw_preview = result.get("preview")
    preview = (
        PreviewUpdatedData.model_validate(raw_preview) if isinstance(raw_preview, dict) else None
    )
    return StopSessionResponse(
        status=result["status"],
        interrupted=bool(result.get("interrupted")),
        kept=bool(result.get("kept")),
        awaiting_image_ok=bool(result.get("awaiting_image_ok")),
        awaiting_angle_pick=bool(result.get("awaiting_angle_pick")),
        preview=preview,
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

    # ADR 0047 §13 — fork shares attachments by reference: a join row for
    # every attachment the copied messages reference keeps digests hydrating
    # and tells GC the file is still in use.
    referenced_ids: set[uuid.UUID] = set()
    for m in copied:
        referenced_ids.update(_attachment_ids_of(m))
    if referenced_ids:
        live_ids = set(
            (await db.scalars(select(Attachment.id).where(Attachment.id.in_(referenced_ids)))).all()
        )
        for attachment_id in live_ids:
            if await db.get(AttachmentSession, (attachment_id, fork.id)) is None:
                db.add(AttachmentSession(attachment_id=attachment_id, session_id=fork.id))

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
        messages=await _messages_response(db, new_msgs),
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
    messages = await _messages_response(db, msgs)
    for resp, m in zip(messages, msgs, strict=True):
        resp.forks = [
            ForkRef(session_id=f.id, title=f.title, created_at=f.created_at)
            for f in forks_by_message.get(m.id, [])
        ]

    parked_angle = bool(state.get("awaiting_angle_pick"))
    parked_image = bool(state.get("awaiting_image_ok"))
    pick = angle_pick_payload(state) if parked_angle else None
    # Image park returns the locked format so a reload matches this version (ADR 0036).
    locked_format = recommended_image_format(state) if parked_angle or parked_image else None
    return SessionMessagesResponse(
        session=_session_response(session),
        messages=messages,
        brief=_brief_from_state(state),
        awaiting_image_ok=parked_image,
        awaiting_angle_pick=parked_angle,
        personas=pick["personas"] if pick else [],
        recommended_persona=pick["recommended_persona"] if pick else None,
        image_format_options=pick["image_format_options"] if pick else [],
        recommended_image_format=locked_format,
        forked_from=await _fork_origin(db, session),
    )


@router.get("/{session_id}/events")
async def session_events(
    session_id: uuid.UUID,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> StreamingResponse:
    """SSE stream: initial snapshot, then live session events + heartbeats.

    Auth + snapshot use a short-lived session and release the pool connection
    before the stream starts. ``Depends(get_db)`` / ``get_current_user`` would
    hold a connection for the whole SSE lifetime (idle tab / session switch).
    """
    async with open_session() as db:
        user = await resolve_current_user(credentials, db)
        session = await _require_owned_session(db, session_id, user)
        draft = await repos.get_latest_preview_draft(db, session.id)
        state = session.state or {}
        copy = normalize_draft_copy((draft.copy if draft else None) or state.get("draft"))
        platform = (draft.platform if draft else None) or DEFAULT_PLATFORM
        media_items = await list_latest_session_media(db, session)

        interrupted = _parked_node_from_snapshot(state, ()) is not None
        try:
            from internal.session.graph import get_session_graph

            graph = get_session_graph()
            snap = await graph.aget_state({"configurable": {"thread_id": str(session.id)}})
            interrupted = _parked_node_from_snapshot(state, snap.next) is not None
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
            "image_url": resolve_stored_url(draft.image_url if draft else state.get("image_url")),
            "media": media_items,
            "copy": copy,
            "platform": platform,
            "interrupted": interrupted,
            # ADR 0038: resolved grounding for the Sources block (draft row wins).
            "source_signals": await resolve_source_signals(
                db,
                list(draft.source_signal_ids or [])
                if draft
                else list(state.get("source_signal_ids") or []),
            ),
        }
        receipt_row = await repos.get_latest_publish_receipt(db, session.id)
        if receipt_row:
            snapshot_data["confirm_receipt"] = _confirm_response(receipt_row).model_dump(
                mode="json"
            )

    async def event_stream() -> AsyncIterator[str]:
        yield format_sse("session.snapshot", snapshot_data)
        async for ev in session_event_bus.subscribe(session_id):
            if await request.is_disconnected():
                break
            yield format_sse(str(ev["type"]), ev.get("data") or {})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # No `Connection` header — hop-by-hop headers are a protocol
            # violation on HTTP/2 (RFC 9113 §8.2.2) and ACA ingress serves
            # h2 to browsers; a leaked `keep-alive` resets the stream with
            # ERR_HTTP2_PROTOCOL_ERROR.
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
        source_signals=[
            SourceSignal.model_validate(s) for s in (result.get("source_signals") or [])
        ],
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
        awaiting_image_ok=bool(result.get("awaiting_image_ok")),
        source_signals=[
            SourceSignal.model_validate(s) for s in (result.get("source_signals") or [])
        ],
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
    return SessionMediaListResponse(media=[PreviewMediaItem.model_validate(m) for m in items])


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
    await _enforce_member_token_limit(db, session, user)
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


# --- Session scratch attachments (ADR 0047) ------------------------------------

_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # ADR 0047 §4 cap (10–20 MB/file)
_SESSION_SCRATCH_CAP = 10  # ADR 0047 §14 — bound digest tokens per session
_ATTACHMENT_ALLOWED_EXTS = {".pdf", ".docx", ".txt", ".md"}
# ADR 0047 §12 — spreadsheets stay product-path only; steer, never ingest.
_ATTACHMENT_SPREADSHEET_EXTS = {".csv", ".xlsx"}
_ATTACHMENT_INGEST_KIND = "attachment_ingest"


def _attachment_out(row: Attachment) -> AttachmentOut:
    return AttachmentOut.model_validate(row)


@router.get("/{session_id}/attachments", response_model=AttachmentListResponse)
async def list_session_attachments(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AttachmentListResponse:
    """List the attachments this session references (ADR 0047 Consequences —
    ``POST/GET …/sessions/{id}/attachments``). The only wire-level way for
    the UI to poll ingest ``status``, the §10 ``error`` text and the §5
    ``doc_profile`` digest; hydration reads the ``attachment_sessions`` join
    (§13), so fork-shared and saved library docs still show up."""
    session = await _require_owned_session(db, session_id, user)
    rows = await repos.list_session_attachments(db, session.id)
    return AttachmentListResponse(attachments=[_attachment_out(r) for r in rows])


@router.post(
    "/{session_id}/attachments",
    response_model=AttachmentOut,
    status_code=201,
)
async def post_session_attachment(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File(...)],
) -> AttachmentOut:
    """Upload a scratch document (ADR 0047 §3).

    Bytes land under ``attachments/{id}/{filename}``; parse/chunk/embed run on
    the ADR 0039 job queue — never in this request (§7, no embedder warmup
    here either). The unauthenticated ``GET /api/media/{key}`` route never
    serves these keys; original bytes are behind
    ``GET /api/attachments/{id}/download``.
    """
    session = await _require_owned_session(db, session_id, user)

    # Sniff by filename extension (case-insensitive); content_type is advisory.
    filename = Path(file.filename or "").name or "attachment"
    ext = Path(filename).suffix.lower()
    if ext in _ATTACHMENT_SPREADSHEET_EXTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Spreadsheet files stay on the product import path — use "
                f"POST /api/companies/{session.company_id}/products/import"
            ),
        )
    if ext not in _ATTACHMENT_ALLOWED_EXTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type — attachments accept pdf, docx, txt, md",
        )

    raw = await file.read()
    if len(raw) > _MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attachment exceeds the 20 MB size limit",
        )

    scratch_count = await db.scalar(
        select(func.count())
        .select_from(Attachment)
        .where(
            Attachment.session_id == session.id,
            Attachment.owner_scope == "session",
        )
    )
    if (scratch_count or 0) >= _SESSION_SCRATCH_CAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session attachment limit reached",
        )

    attachment_id = uuid.uuid4()
    object_key = f"attachments/{attachment_id}/{filename}"
    content_type = file.content_type or "application/octet-stream"
    try:
        await put_bytes(key=object_key, data=raw, content_type=content_type)
    except MediaStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    attachment = Attachment(
        id=attachment_id,
        company_id=session.company_id,
        owner_scope="session",
        user_id=user.id,
        session_id=session.id,
        filename=filename,
        content_type=content_type,
        object_key=object_key,
        status="pending",
        doc_profile={},
    )
    db.add(attachment)
    db.add(AttachmentSession(attachment_id=attachment_id, session_id=session.id))
    await repos.enqueue_job(
        db,
        kind=_ATTACHMENT_INGEST_KIND,
        payload={"attachment_id": str(attachment_id)},
        dedupe_key=f"{_ATTACHMENT_INGEST_KIND}:{attachment_id}",
    )
    await db.commit()
    await db.refresh(attachment)
    return _attachment_out(attachment)


def _draft_has_image(draft) -> bool:
    # media_ids is the publish image (ADR 0008). A leftover placeholder://
    # image_url is not an image — copy-only Confirm must 400 (ADR 0022).
    # A stored object key counts as an image (ADR 0024).
    if list(draft.media_ids or []):
        return True
    return stored_ref_is_image(draft.image_url)


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

    # ADR 0041: org policy can park a member's Confirm for owner/admin approval.
    # Owner/admin always publish directly; the policy defaults off.
    membership = await repos.get_org_membership(db, user.id, session.company_id)
    if membership is not None and membership.role == "member":
        company = await repos.get_company(db, session.company_id)
        if member_publish_requires_approval(company.profile if company else None):
            receipt = await repos.create_tool_receipt(
                db,
                session_id=session.id,
                user_id=user.id,
                tool_name=repos.PUBLISH_TOOL_NAME,
                idempotency_key=body.idempotency_key,
                status=repos.PUBLISH_PENDING_APPROVAL,
                request={
                    "platform": body.platform,
                    "approval_token": body.approval_token,
                    "revision": draft.revision,
                    "copy": normalize_draft_copy(draft.copy),
                    "media_ids": [str(i) for i in (draft.media_ids or [])],
                    "image_url": draft.image_url,
                },
                response={},
            )
            # Only the latest parked revision stays in the queue.
            await repos.supersede_pending_publish_approvals(
                db, session_id=session.id, exclude_receipt_id=receipt.id
            )
            await db.commit()
            await session_event_bus.publish(
                session.id,
                "confirm.completed",
                {
                    "receipt_id": str(receipt.id),
                    "status": receipt.status,
                    "tool_name": receipt.tool_name,
                    "idempotency_key": receipt.idempotency_key,
                    "permalink": None,
                    "error_kind": None,
                },
            )
            return _confirm_response(receipt)

    image_url = await resolve_publish_image_url(db, draft.media_ids, draft.image_url)
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
        outcome, receipt = await execute_publish(db, session=session, user_id=user.id, req=req)
    except PublishPreconditionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.detail,
        ) from exc
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
