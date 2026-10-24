"""MCP tool handlers (ADR 0051 §7–§10).

Thin adapter over the session service — same calls REST makes, plus a
deterministic auto-drive that answers the parked gates without an LLM.
Mutating tools spawn a background turn and return ``status: "running"``;
``get_post_draft`` is the client source of truth (mirrors ADR 0002).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from internal.instance.config import get_snapshot
from internal.memory import repos
from internal.memory.database import open_session
from internal.memory.models import Session
from internal.session import service
from internal.session.guards import enforce_member_token_limit, require_owned_session
from internal.session.nodes import angle_pick_payload
from internal.session.turn_registry import session_turn_registry
from schemas.contracts import DraftCopy, PreviewMediaItem
from schemas.mcp import (
    AwaitingAnglePick,
    AwaitingImageOk,
    AwaitingReply,
    BrandContextResult,
    BrandProductSummary,
    ChooseAngleArgs,
    DraftCancelled,
    DraftFailed,
    DraftReady,
    PostDraftState,
    ReadyPreview,
    RevisePostDraftArgs,
    SessionToolArgs,
    StartPostDraftArgs,
    TurnStarted,
    VoiceDigest,
)

from .auth import McpContext
from .errors import ToolRefusal

logger = logging.getLogger(__name__)

GATE_ANGLE = "angle"
GATE_IMAGE = "image"
TURN_ERROR_KEY = "mcp_turn_error"
TURN_ERROR_REVISION_KEY = "mcp_turn_error_revision"


async def get_brand_context(ctx: McpContext) -> BrandContextResult:
    """Read-only digest — voice + product names, never a raw catalog dump."""
    from internal.session.voice import voice_pack

    async with open_session() as db:
        company = await repos.get_company(db, ctx.claims.company_id)
        products = await repos.list_products(
            db, company_id=ctx.claims.company_id, owner_scope="org"
        )
    return BrandContextResult(
        company_name=company.name if company else "",
        voice=VoiceDigest.model_validate(voice_pack(company.profile if company else None)),
        products=[BrandProductSummary(name=p.name, summary=_product_summary(p)) for p in (products or [])],
    )


def _product_summary(p: Any) -> str:
    """One-line summary from profile notes/description (ADR 0051 §7)."""
    profile = p.profile if isinstance(getattr(p, "profile", None), dict) else {}
    return str(profile.get("notes") or profile.get("description") or "").strip()[:200]


async def _load_session(db: AsyncSession, ctx: McpContext, session_id: uuid.UUID) -> Session:
    """Ownership + company binding (§6) — raises SessionGuardError."""
    return await require_owned_session(
        db, session_id, ctx.claims.user_id, company_id=ctx.claims.company_id
    )


def _confirm_url(session_id: uuid.UUID) -> str:
    return f"{get_snapshot().web_base_url}/sessions/{session_id}"


# Turns spawned by this adapter, keyed by session. The registry only knows a
# turn once `run_session_turn` calls `begin()` — this map closes the gap
# between `create_task` and `begin`, and covers the whole auto-drive run.
_pending_turns: dict[uuid.UUID, asyncio.Task] = {}
# §13 — session → grant, so a grant can't run too many drafts at once.
_pending_grants: dict[uuid.UUID, uuid.UUID] = {}
GRANT_MAX_CONCURRENT = 3


def _is_turn_pending(session_id: uuid.UUID) -> bool:
    task = _pending_turns.get(session_id)
    return task is not None and not task.done()


def _grant_running_count(grant_id: uuid.UUID) -> int:
    return sum(
        1 for sid, gid in _pending_grants.items() if gid == grant_id and _is_turn_pending(sid)
    )


def _spawn_turn(session_id: uuid.UUID, coro, grant_id: uuid.UUID | None = None) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _pending_turns[session_id] = task
    if grant_id is not None:
        _pending_grants[session_id] = grant_id
    task.add_done_callback(lambda done: _on_turn_done(session_id, done))
    return task


def _on_turn_done(session_id: uuid.UUID, task: asyncio.Task) -> None:
    if _pending_turns.get(session_id) is task:
        _pending_turns.pop(session_id, None)
        _pending_grants.pop(session_id, None)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is None:
        return
    logger.warning("MCP session turn failed", exc_info=exc)
    # loop already closing → error reporting is best-effort
    with contextlib.suppress(RuntimeError):
        asyncio.get_running_loop().create_task(_record_turn_error(session_id, exc))


async def _record_turn_error(session_id: uuid.UUID, exc: BaseException) -> None:
    """Persist the failure so get_post_draft reports `failed`, not `ready`."""
    try:
        async with open_session() as db:
            session = await repos.get_session(db, session_id)
            if session is None:
                return
            state = session.state or {}
            # Stamp the revision: a completed turn rebuilds state (dropping
            # these keys), but non-turn edits copy state and bump the revision.
            session.state = {
                **state,
                TURN_ERROR_KEY: str(exc),
                TURN_ERROR_REVISION_KEY: state.get("revision"),
            }
            await db.commit()
    except Exception:
        logger.warning("could not persist MCP turn error", exc_info=True)


def _live_turn_error(state: dict[str, Any]) -> str | None:
    """The recorded failure, unless a later edit moved the draft past it."""
    error = state.get(TURN_ERROR_KEY)
    if not error:
        return None
    if state.get(TURN_ERROR_REVISION_KEY, state.get("revision")) != state.get("revision"):
        return None
    return str(error)


def _clear_turn_error(session: Session) -> None:
    state = session.state or {}
    if TURN_ERROR_KEY in state or TURN_ERROR_REVISION_KEY in state:
        session.state = {
            k: v for k, v in state.items() if k not in (TURN_ERROR_KEY, TURN_ERROR_REVISION_KEY)
        }


def _compose_content(brief: str, context: str | None) -> str:
    """External context enters as user-turn data, never as instructions."""
    return brief if context is None else f"{brief}\n\nContext:\n{context}"


async def _run_session_turn_bg(session_id: uuid.UUID, *, user_content: str) -> None:
    async with open_session() as db:
        session = await repos.get_session(db, session_id)
        if session is None:
            return
        _clear_turn_error(session)
        await service.run_session_turn(db, session, user_content=user_content)
        await db.commit()


async def _auto_drive(
    session_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    scopes: set[str],
    persona: str | None,
    image_format: str | None,
    brief: str,
    context: str | None,
) -> None:
    """Deterministic gate answerer (§10): at most one auto answer per gate."""
    answered: set[str] = set()
    picks: dict[str, Any] = {}
    content = _compose_content(brief, context)
    try:
        await _run_session_turn_bg(session_id, user_content=content)
        while True:
            async with open_session() as db:
                session = await repos.get_session(db, session_id)
                if session is None:
                    return
                kind = await service.session_park_kind(session)
                if kind == GATE_ANGLE and GATE_ANGLE not in answered:
                    answered.add(GATE_ANGLE)
                    # ADR 0041 — every turn re-checks the member cap, same as REST.
                    await enforce_member_token_limit(db, session, user_id)
                    payload = angle_pick_payload(session.state or {})
                    offered = payload.get("angles") or []
                    index = payload.get("recommended_angle_index")
                    if not isinstance(index, int) or not (0 <= index < len(offered)):
                        index = 0
                    # Record the *effective* picks — caller values win, then
                    # the park's own recommendations (§10).
                    eff_persona = persona or payload.get("recommended_persona")
                    eff_format = image_format or payload.get("recommended_image_format")
                    picks.update(
                        {
                            "angle_index": index,
                            "persona": eff_persona,
                            "image_format": eff_format,
                        }
                    )
                    await service.choose_angle_turn(
                        db,
                        session,
                        angle_index=index,
                        persona=eff_persona,
                        image_format=eff_format,
                    )
                    await db.commit()
                    continue
                if kind == GATE_IMAGE and GATE_IMAGE not in answered:
                    if "images:generate" not in scopes:
                        break
                    answered.add(GATE_IMAGE)
                    await enforce_member_token_limit(db, session, user_id)
                    picks["image_approved"] = True
                    await service.resume_image_turn(db, session)
                    await db.commit()
                    continue
                break
    finally:
        await _record_auto_picks(session_id, picks)


async def _record_auto_picks(session_id: uuid.UUID, picks: dict[str, Any]) -> None:
    if not picks:
        return
    picks.setdefault("image_approved", False)
    async with open_session() as db:
        session = await repos.get_session(db, session_id)
        if session is None:
            return
        session.origin = {**(session.origin or {}), "auto_picks": picks}
        await db.commit()


async def start_post_draft(ctx: McpContext, args: StartPostDraftArgs) -> TurnStarted:
    """Create the grant-owned session, then run turns in the background."""
    if _grant_running_count(ctx.claims.grant_id) >= GRANT_MAX_CONCURRENT:
        raise ToolRefusal(
            "rate_limited", f"Too many concurrent drafts for this app (max {GRANT_MAX_CONCURRENT})"
        )
    async with open_session() as db:
        session = await repos.create_session(
            db, user_id=ctx.claims.user_id, company_id=ctx.claims.company_id
        )
        session.origin = {
            "kind": "mcp",
            "grant_id": str(ctx.claims.grant_id),
            "client_id": ctx.grant.client_id,
            "client_name": ctx.grant.client_name,
        }
        # ADR 0041 — cap check BEFORE commit so an over-limit member never
        # leaves an orphan session behind.
        await enforce_member_token_limit(db, session, ctx.claims.user_id)
        await db.commit()

    if args.auto:
        _spawn_turn(
            session.id,
            _auto_drive(
                session.id,
                user_id=ctx.claims.user_id,
                scopes=ctx.scopes,
                persona=args.persona,
                image_format=args.image_format,
                brief=args.brief,
                context=args.context,
            ),
            grant_id=ctx.claims.grant_id,
        )
    else:
        _spawn_turn(
            session.id,
            _run_session_turn_bg(
                session.id, user_content=_compose_content(args.brief, args.context)
            ),
            grant_id=ctx.claims.grant_id,
        )
    return TurnStarted(session_id=session.id)


async def get_post_draft(ctx: McpContext, args: SessionToolArgs) -> PostDraftState:
    """The client source of truth (§8): status + the payload for that status."""
    async with open_session() as db:
        session = await _load_session(db, ctx, args.session_id)

        if session_turn_registry.is_busy(session.id) or _is_turn_pending(session.id):
            return TurnStarted(session_id=session.id)

        state = session.state or {}
        kind = await service.session_park_kind(session)
        if kind == GATE_ANGLE:
            return AwaitingAnglePick.model_validate(
                {**angle_pick_payload(state), "session_id": session.id}
            )
        if kind == GATE_IMAGE:
            return AwaitingImageOk(
                session_id=session.id,
                copy=DraftCopy.model_validate(state.get("draft") or {}),
                image_plan=state.get("image_plan"),
            )
        error = _live_turn_error(state) or state.get("error")
        if error:
            return DraftFailed(session_id=session.id, error=str(error))

        messages = await repos.list_session_messages(db, session.id)
        preview = await service.latest_preview_payload(db, session)
    # Surface the last assistant turn output so a question asked after the
    # preview exists is not hidden behind `ready`.
    last = next((m for m in reversed(messages) if m.role == "assistant"), None)
    if preview:
        # §12 — approval_token never leaves the server.
        return DraftReady(
            session_id=session.id,
            confirm_url=_confirm_url(session.id),
            message=last.content if last else None,
            preview=ReadyPreview(
                copy=DraftCopy.model_validate(preview.get("copy") or {}),
                image_url=preview.get("image_url"),
                media=[
                    PreviewMediaItem.model_validate(m) for m in (preview.get("media") or [])
                ],
            ),
        )

    # Turn ended without a park or preview — the assistant asked or said
    # something. Surface it so the client can answer via revise_post_draft.
    return AwaitingReply(session_id=session.id, message=last.content if last else None)


def _assert_not_busy(session_id: uuid.UUID) -> None:
    """§8 — a mutating call while a turn runs answers a tool error."""
    if session_turn_registry.is_busy(session_id) or _is_turn_pending(session_id):
        raise ToolRefusal(
            "turn_in_flight", "A turn is still running — poll get_post_draft for state"
        )


async def _spawn_resume(
    ctx: McpContext, args: SessionToolArgs, expected_park: str, runner
) -> TurnStarted:
    """Shared prelude for choose/approve: guard + park check + background turn."""
    async with open_session() as db:
        session = await _load_session(db, ctx, args.session_id)
        _assert_not_busy(session.id)
        kind = await service.session_park_kind(session)
        if kind != expected_park:
            raise ToolRefusal(
                "invalid_state",
                f"Session is not parked at {expected_park} (currently {kind or 'not parked'})",
            )
        await enforce_member_token_limit(db, session, ctx.claims.user_id)
        session_id = session.id

    _spawn_turn(session_id, runner(session_id), grant_id=ctx.claims.grant_id)
    return TurnStarted(session_id=session_id)


async def choose_angle(ctx: McpContext, args: ChooseAngleArgs) -> TurnStarted:
    if args.angle_index is None and not (args.angle or args.feedback):
        raise ToolRefusal("invalid_params", "Provide angle_index, angle or feedback")

    async def run(session_id: uuid.UUID) -> None:
        async with open_session() as db:
            session = await repos.get_session(db, session_id)
            if session is None:
                return
            _clear_turn_error(session)
            await service.choose_angle_turn(
                db,
                session,
                angle_index=args.angle_index,
                angle_text=(args.feedback or args.angle),
                persona=args.persona,
                image_format=args.image_format,
            )
            await db.commit()

    return await _spawn_resume(ctx, args, GATE_ANGLE, run)


async def approve_image(ctx: McpContext, args: SessionToolArgs) -> TurnStarted:
    async def run(session_id: uuid.UUID) -> None:
        async with open_session() as db:
            session = await repos.get_session(db, session_id)
            if session is None:
                return
            _clear_turn_error(session)
            await service.resume_image_turn(db, session)
            await db.commit()

    return await _spawn_resume(ctx, args, GATE_IMAGE, run)


async def revise_post_draft(ctx: McpContext, args: RevisePostDraftArgs) -> TurnStarted:
    """A revise message — plain turn, typed angle pick, or image-park re-script."""
    session_id = args.session_id
    async with open_session() as db:
        session = await _load_session(db, ctx, session_id)
        _assert_not_busy(session_id)
        await enforce_member_token_limit(db, session, ctx.claims.user_id)

    _spawn_turn(
        session_id,
        _run_session_turn_bg(session_id, user_content=args.instruction),
        grant_id=ctx.claims.grant_id,
    )
    return TurnStarted(session_id=session_id)


async def cancel_post_draft(ctx: McpContext, args: SessionToolArgs) -> DraftCancelled:
    """Stop semantics (ADR 0004): cancel in-flight, discard the parked turn."""
    async with open_session() as db:
        session = await _load_session(db, ctx, args.session_id)
        await service.stop_session_turn(db, session)
        await db.commit()
    return DraftCancelled(session_id=args.session_id)
