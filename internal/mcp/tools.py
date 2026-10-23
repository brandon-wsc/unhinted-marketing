"""MCP tool handlers (ADR 0051 §7–§10).

Thin adapter over the session service — same calls REST makes, plus a
deterministic auto-drive that answers the parked gates without an LLM.
Mutating tools spawn a background turn and return ``status: "running"``;
``get_post_draft`` is the client source of truth (mirrors ADR 0002).
"""

from __future__ import annotations

import asyncio
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
from schemas.mcp import (
    ChooseAngleArgs,
    RevisePostDraftArgs,
    SessionToolArgs,
    StartPostDraftArgs,
)

from .auth import McpContext

logger = logging.getLogger(__name__)

GATE_ANGLE = "angle"
GATE_IMAGE = "image"


async def get_brand_context(ctx: McpContext) -> dict[str, Any]:
    """Read-only digest — voice + product names, never a raw catalog dump."""
    from internal.session.voice import voice_pack

    async with open_session() as db:
        company = await repos.get_company(db, ctx.claims.company_id)
        products = await repos.list_products(
            db, company_id=ctx.claims.company_id, owner_scope="org"
        )
    return {
        "company_name": company.name if company else "",
        "voice": voice_pack(company.profile if company else None),
        "products": [{"name": p.name, "sku": p.sku} for p in (products or [])],
    }


async def _load_session(db: AsyncSession, ctx: McpContext, session_id: uuid.UUID) -> Session:
    """Ownership + company binding (§6) — raises SessionGuardError."""
    return await require_owned_session(
        db, session_id, ctx.claims.user_id, company_id=ctx.claims.company_id
    )


def _confirm_url(session_id: uuid.UUID) -> str:
    return f"{get_snapshot().web_base_url}/sessions/{session_id}"


def _spawn_turn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    task.add_done_callback(_log_turn_failure)
    return task


def _log_turn_failure(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("MCP session turn failed", exc_info=exc)


async def _run_session_turn_bg(session_id: uuid.UUID, *, user_content: str) -> None:
    async with open_session() as db:
        session = await repos.get_session(db, session_id)
        if session is None:
            return
        await service.run_session_turn(db, session, user_content=user_content)
        await db.commit()


async def _auto_drive(
    session_id: uuid.UUID,
    *,
    scopes: set[str],
    persona: str | None,
    image_format: str | None,
    brief: str,
    context: str | None,
) -> None:
    """Deterministic gate answerer (§10): at most one auto answer per gate."""
    answered: set[str] = set()
    picks: dict[str, Any] = {}
    content = brief if context is None else f"{brief}\n\nContext:\n{context}"
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
                    brief_state = (session.state or {}).get("brief") or {}
                    offered = brief_state.get("angles") or []
                    index = brief_state.get("recommended_angle_index")
                    if not isinstance(index, int) or not (0 <= index < len(offered)):
                        index = 0
                    picks.update(
                        {
                            "angle_index": index,
                            "persona": persona,
                            "image_format": image_format,
                        }
                    )
                    await service.choose_angle_turn(
                        db,
                        session,
                        angle_index=index,
                        persona=persona,
                        image_format=image_format,
                    )
                    await db.commit()
                    continue
                if kind == GATE_IMAGE and GATE_IMAGE not in answered:
                    if "images:generate" not in scopes:
                        break
                    answered.add(GATE_IMAGE)
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


async def start_post_draft(ctx: McpContext, args: StartPostDraftArgs) -> dict[str, Any]:
    """Create the grant-owned session, then run turns in the background."""
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
        await db.commit()

        await enforce_member_token_limit(db, session, ctx.claims.user_id)

    if args.auto:
        _spawn_turn(
            _auto_drive(
                session.id,
                scopes=ctx.scopes,
                persona=args.persona,
                image_format=args.image_format,
                brief=args.brief,
                context=args.context,
            )
        )
    else:
        content = (
            args.brief if args.context is None else f"{args.brief}\n\nContext:\n{args.context}"
        )
        _spawn_turn(_run_session_turn_bg(session.id, user_content=content))
    return {"session_id": session.id, "status": "running"}


async def _awaiting_angle_payload(session: Session) -> dict[str, Any]:
    payload = angle_pick_payload(session.state or {})
    payload.pop("awaiting", None)
    brief = (session.state or {}).get("brief") or {}
    payload["recommended_angle_index"] = brief.get("recommended_angle_index")
    return payload


async def get_post_draft(ctx: McpContext, args: SessionToolArgs) -> dict[str, Any]:
    """The client source of truth (§8): status + the payload for that status."""
    async with open_session() as db:
        session = await _load_session(db, ctx, args.session_id)

        if session_turn_registry.is_busy(session.id):
            return {"session_id": session.id, "status": "running"}

        state = session.state or {}
        kind = await service.session_park_kind(session)
        result: dict[str, Any] = {"session_id": session.id}
        if kind == GATE_ANGLE:
            return {
                **result,
                "status": "awaiting_angle_pick",
                **await _awaiting_angle_payload(session),
            }
        if kind == GATE_IMAGE:
            return {
                **result,
                "status": "awaiting_image_ok",
                "copy": state.get("draft"),
                "image_plan": state.get("image_plan"),
            }
        if state.get("error"):
            return {**result, "status": "failed", "error": str(state["error"])}

        preview = await service.latest_preview_payload(db, session)
    ready: dict[str, Any] = {"status": "ready", "confirm_url": _confirm_url(session.id)}
    if preview:
        # §12 — approval_token never leaves the server.
        ready["preview"] = {
            "copy": preview.get("copy"),
            "image_url": preview.get("image_url"),
            "media": preview.get("media"),
        }
    return {**result, **ready}


async def _spawn_resume(
    ctx: McpContext, args: SessionToolArgs, expected_park: str, runner
) -> dict[str, Any]:
    """Shared prelude for choose/approve: guard + park check + background turn."""
    async with open_session() as db:
        session = await _load_session(db, ctx, args.session_id)
        kind = await service.session_park_kind(session)
        if kind != expected_park:
            from internal.mcp.errors import ToolRefusal

            raise ToolRefusal(
                "invalid_state",
                f"Session is not parked at {expected_park} (currently {kind or 'not parked'})",
            )
        await enforce_member_token_limit(db, session, ctx.claims.user_id)
        session_id = session.id

    _spawn_turn(runner(session_id))
    return {"session_id": session_id, "status": "running"}


async def choose_angle(ctx: McpContext, args: ChooseAngleArgs) -> dict[str, Any]:
    if args.angle_index is None and not (args.angle or args.feedback):
        from internal.mcp.errors import ToolRefusal

        raise ToolRefusal("invalid_params", "Provide angle_index, angle or feedback")

    async def run(session_id: uuid.UUID) -> None:
        async with open_session() as db:
            session = await repos.get_session(db, session_id)
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


async def approve_image(ctx: McpContext, args: SessionToolArgs) -> dict[str, Any]:
    async def run(session_id: uuid.UUID) -> None:
        async with open_session() as db:
            session = await repos.get_session(db, session_id)
            await service.resume_image_turn(db, session)
            await db.commit()

    return await _spawn_resume(ctx, args, GATE_IMAGE, run)


async def revise_post_draft(ctx: McpContext, args: RevisePostDraftArgs) -> dict[str, Any]:
    """A revise message — plain turn, typed angle pick, or image-park re-script."""
    session_id = args.session_id
    async with open_session() as db:
        session = await _load_session(db, ctx, session_id)
        await enforce_member_token_limit(db, session, ctx.claims.user_id)

    _spawn_turn(_run_session_turn_bg(session_id, user_content=args.instruction))
    return {"session_id": session_id, "status": "running"}


async def cancel_post_draft(ctx: McpContext, args: SessionToolArgs) -> dict[str, Any]:
    """Stop semantics (ADR 0004): cancel in-flight, discard the parked turn."""
    async with open_session() as db:
        session = await _load_session(db, ctx, args.session_id)
        await service.stop_session_turn(db, session)
        await db.commit()
    return {"session_id": args.session_id, "status": "cancelled"}
