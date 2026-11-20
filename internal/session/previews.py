"""Preview/draft payload assembly and draft writes for session routes and turn plumbing."""

from __future__ import annotations

import copy
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from internal.media.storage import resolve_stored_url
from internal.memory import repos
from internal.memory.models import (
    PreviewImage,
    Session,
)
from internal.session import graph_state
from internal.session.events import session_event_bus
from internal.session.graph import (
    get_session_graph,
)
from internal.session.media import image_format_from_plan, media_item_payload
from internal.session.state import MODE_PREVIEW
from schemas.contracts import (
    DraftCopy,
    PreviewMediaItem,
    PreviewUpdatedData,
    SourceSignal,
)

logger = logging.getLogger(__name__)

DEFAULT_PLATFORM = "instagram"
async def list_latest_session_media(db: AsyncSession, session: Session) -> list[dict[str, Any]]:
    draft = await repos.get_latest_preview_draft(db, session.id)
    ids = list(draft.media_ids or []) if draft else []
    if not ids:
        state_ids = (session.state or {}).get("media_ids") or []
        ids = [uuid.UUID(str(i)) for i in state_ids]
    rows = await repos.get_preview_images_by_ids(db, ids)
    media, _, _ = _payloads_from_image_rows(rows)
    return media


def normalize_draft_copy(copy: dict[str, Any] | None) -> dict[str, Any]:
    raw = copy or {}
    hashtags = raw.get("hashtags") or []
    if not isinstance(hashtags, list):
        hashtags = []
    return DraftCopy(
        caption=str(raw.get("caption") or ""),
        hashtags=[str(h) for h in hashtags if str(h).strip()],
        cta=str(raw.get("cta") or ""),
    ).model_dump()


async def resolve_source_signals(db: AsyncSession, signal_ids: list[Any]) -> list[dict[str, Any]]:
    """Resolve draft grounding ids to display rows, preserving draft order (ADR 0038).

    Best-effort: missing rows are dropped, a failed lookup yields [] — never a
    failed preview payload.
    """
    ids = [str(s) for s in (signal_ids or []) if s]
    if not ids:
        return []
    try:
        rows = await repos.get_signals_by_ids(db, ids)
    except Exception:
        logger.debug("source signal lookup failed", exc_info=True)
        return []
    by_id = {r.signal_id: r for r in rows}
    return [
        {
            "signal_id": row.signal_id,
            "source": row.source,
            "title": row.title,
            "url": row.url,
            "excerpt": row.excerpt,
        }
        for row in (by_id[i] for i in ids if i in by_id)
    ]


def preview_updated_payload(
    *,
    revision: int,
    approval_token: str,
    image_url: str | None,
    copy: dict[str, Any] | None,
    platform: str | None = None,
    media: list[dict[str, Any]] | None = None,
    source_signals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    items = [PreviewMediaItem.model_validate(m) for m in (media or [])]
    primary = resolve_stored_url(image_url)
    if primary is None and items:
        primary = items[0].url
    return PreviewUpdatedData(
        revision=revision,
        approval_token=approval_token,
        image_url=primary,
        media=items,
        draft_copy=DraftCopy.model_validate(normalize_draft_copy(copy)),
        platform=platform or DEFAULT_PLATFORM,
        source_signals=[SourceSignal.model_validate(s) for s in (source_signals or [])],
    ).model_dump(by_alias=True)


def _coerce_preview_draft(
    draft: Any,
) -> tuple[int, str, dict[str, Any], str | None, dict[str, Any] | None, list[Any], str] | None:
    """Real preview row fields, or None for a missing / non-row stand-in."""
    if draft is None:
        return None
    revision = getattr(draft, "revision", None)
    token = getattr(draft, "approval_token", None)
    if not isinstance(revision, int) or not isinstance(token, str) or not token:
        return None
    copy = getattr(draft, "copy", None)
    if not isinstance(copy, dict):
        copy = {}
    image_url = getattr(draft, "image_url", None)
    if not isinstance(image_url, str):
        image_url = None
    plan = getattr(draft, "image_plan", None)
    if not isinstance(plan, dict):
        plan = None
    media_ids = getattr(draft, "media_ids", None)
    if not isinstance(media_ids, list):
        media_ids = []
    platform = getattr(draft, "platform", None)
    if not isinstance(platform, str) or not platform:
        platform = DEFAULT_PLATFORM
    return revision, token, copy, image_url, plan, media_ids, platform


def _discard_revision_ceiling(restored: dict[str, Any], accepted_revision: int | None) -> int:
    """Highest revision Discard keeps.

    Prefer the lower of the anchor's ``accepted_revision`` and the pre-turn
    ``revision`` so a pending number on either field still drops the unexecuted
    row (ADR 0036).
    """
    raw = restored.get("revision")
    state_rev = raw if isinstance(raw, int) else None
    explicit = accepted_revision if isinstance(accepted_revision, int) else None
    if explicit is not None and state_rev is not None:
        return min(explicit, state_rev)
    if explicit is not None:
        return explicit
    if state_rev is not None:
        return state_rev
    return 0


def _apply_surviving_draft(restored: dict[str, Any], draft: Any) -> None:
    """Copy the surviving preview row onto session state after a discard."""
    parsed = _coerce_preview_draft(draft)
    if parsed is None:
        return
    revision, token, copy, image_url, plan, media_ids, _platform = parsed
    restored["draft"] = normalize_draft_copy(copy)
    restored["revision"] = revision
    restored["approval_token"] = token
    restored["image_url"] = image_url
    if plan is not None:
        restored["image_plan"] = plan
        restored["image_format"] = image_format_from_plan(
            plan, fallback=str(restored.get("image_format") or "single")
        )
    ids: list[str] = []
    for raw_id in media_ids:
        if isinstance(raw_id, uuid.UUID):
            ids.append(str(raw_id))
        elif isinstance(raw_id, str):
            ids.append(raw_id)
    restored["media_ids"] = ids


async def latest_preview_payload(db: AsyncSession, session: Session) -> dict[str, Any] | None:
    """`preview.updated` body for the latest draft, or None when there is no row."""
    draft = await repos.get_latest_preview_draft(db, session.id)
    parsed = _coerce_preview_draft(draft)
    if parsed is None:
        return None
    revision, token, copy, image_url, _plan, _media_ids, platform = parsed
    media: list[dict[str, Any]] = []
    try:
        loaded = await list_latest_session_media(db, session)
    except Exception:
        logger.debug("latest preview media lookup failed", exc_info=True)
        loaded = []
    if isinstance(loaded, list):
        media = [
            item for item in loaded if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
    source_signals = await resolve_source_signals(
        db, list(getattr(draft, "source_signal_ids", None) or [])
    )
    return preview_updated_payload(
        revision=revision,
        approval_token=token,
        image_url=image_url,
        copy=copy,
        platform=platform,
        media=media,
        source_signals=source_signals,
    )


def _payloads_from_image_rows(
    rows: list[PreviewImage],
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any] | None]:
    """HTTP media payloads (resolved URLs) plus raw stored primary for Postgres/graph."""
    media = [
        media_item_payload(
            image_id=r.id,
            url=r.url,
            plan=r.plan,
            format=r.format,
            role=r.role,
            seq=r.seq,
            status=r.status,
        )
        for r in rows
    ]
    if not rows:
        return media, None, None
    primary = rows[0]
    return media, primary.url, dict(primary.plan or {})


async def _media_for_new_draft(
    db: AsyncSession,
    session: Session,
    *,
    image_url: str | None,
    image_plan: dict[str, Any] | None,
    image_format: str | None,
    reuse_media_ids: list[uuid.UUID] | None,
    create_image_row: bool,
) -> tuple[list[uuid.UUID], list[dict[str, Any]], str | None, dict[str, Any] | None]:
    """Resolve media_ids for a new draft revision (ADR 0008).

    - create_image_row: insert append-only preview_images from url/plan (gen path).
    - else reuse_media_ids: caption-only path keeps same image versions.
    """
    if create_image_row and (image_url or image_plan):
        fmt = image_format_from_plan(image_plan, fallback=image_format or "single")
        row = await repos.insert_preview_image(
            db,
            session_id=session.id,
            url=image_url,
            plan=image_plan,
            format=fmt,
            role="primary",
            seq=0,
            status="ready" if image_url else "pending",
        )
        media = [
            media_item_payload(
                image_id=row.id,
                url=row.url,
                plan=row.plan,
                format=row.format,
                role=row.role,
                seq=row.seq,
                status=row.status,
            )
        ]
        return [row.id], media, row.url, dict(row.plan or {})

    ids = list(reuse_media_ids or [])
    rows = await repos.get_preview_images_by_ids(db, ids)
    media, primary_url, primary_plan = _payloads_from_image_rows(rows)
    if primary_url is None:
        primary_url = image_url
    if primary_plan is None:
        primary_plan = image_plan
    return ids, media, primary_url, primary_plan


@dataclass
class ForkPreviewCopy:
    """Facts about a fork's preview copy, for the route to derive preview_note."""

    copied: bool
    copied_revision: int | None
    latest_revision: int | None


async def copy_session_preview(
    db: AsyncSession,
    source: Session,
    target: Session,
    *,
    as_of: datetime | None = None,
) -> ForkPreviewCopy:
    """Copy the source's preview draft + media into a forked session (ADR 0017).

    With ``as_of`` (the fork-point message's created_at) the copy is
    time-aligned: the revision that existed at that moment, or nothing when the
    preview postdates the fork point. The fork restarts at revision=1 with a
    freshly minted approval_token — tokens are never shared across sessions
    (ADR 0003). preview_images rows are duplicated into the target session
    (append-only per ADR 0008; same asset URLs) and media_ids are remapped to
    the new row ids. The copied draft keeps the source row's created_at so the
    timeline stays aligned for fork-of-fork.
    """
    latest = await repos.get_latest_preview_draft(db, source.id)
    draft = (
        await repos.get_preview_draft_as_of(db, source.id, as_of) if as_of is not None else latest
    )
    latest_revision = latest.revision if latest is not None else None
    if draft is None:
        return ForkPreviewCopy(copied=False, copied_revision=None, latest_revision=latest_revision)

    id_map: dict[uuid.UUID, uuid.UUID] = {}
    for img in await repos.get_preview_images_by_ids(db, list(draft.media_ids or [])):
        row = await repos.insert_preview_image(
            db,
            session_id=target.id,
            url=img.url,
            plan=img.plan,
            format=img.format,
            role=img.role,
            seq=img.seq,
            status=img.status,
        )
        id_map[img.id] = row.id
    media_ids = [id_map[i] for i in (draft.media_ids or []) if i in id_map]

    token = secrets.token_urlsafe(24)
    await repos.upsert_preview_draft(
        db,
        session_id=target.id,
        revision=1,
        copy=copy.deepcopy(draft.copy or {}),
        image_url=draft.image_url,
        image_plan=copy.deepcopy(draft.image_plan) if draft.image_plan else None,
        source_signal_ids=list(draft.source_signal_ids or []),
        approval_token=token,
        platform=draft.platform,
        media_ids=media_ids,
        created_at=draft.created_at,
    )

    state: dict[str, Any] = {
        "draft": copy.deepcopy(draft.copy or {}),
        "revision": 1,
        "approval_token": token,
        "image_url": draft.image_url,
        "media_ids": [str(i) for i in media_ids],
        "pending_confirm": False,
        "need_image": False,
        "awaiting_image_ok": False,
    }
    if draft.image_plan is not None:
        state["image_plan"] = copy.deepcopy(draft.image_plan)
    target.state = state
    if source.mode == MODE_PREVIEW:
        target.mode = MODE_PREVIEW
    return ForkPreviewCopy(
        copied=True, copied_revision=draft.revision, latest_revision=latest_revision
    )


async def _backfill_primary_image_row(
    db: AsyncSession,
    session: Session,
    *,
    primary_url: str | None,
    primary_plan: dict[str, Any] | None,
) -> tuple[list[uuid.UUID], list[dict[str, Any]], str | None, dict[str, Any] | None]:
    """Pre-media_ids drafts carry only a loose primary url/plan — materialize the row once."""
    return await _media_for_new_draft(
        db,
        session,
        image_url=primary_url,
        image_plan=primary_plan if isinstance(primary_plan, dict) else None,
        image_format=None,
        reuse_media_ids=None,
        create_image_row=True,
    )


async def update_session_draft(
    db: AsyncSession,
    session: Session,
    *,
    caption: str,
    hashtags: list[str],
    cta: str,
) -> dict[str, Any]:
    """Persist a user manual caption edit in PREVIEW mode — no LangGraph / LLM turn."""
    if session.mode != MODE_PREVIEW:
        raise ValueError("Session is not in PREVIEW mode")

    state = dict(session.state or {})
    copy = normalize_draft_copy({"caption": caption, "hashtags": hashtags, "cta": cta})
    if not copy["caption"].strip():
        raise ValueError("caption is required")

    existing = await repos.get_latest_preview_draft(db, session.id)
    reuse_ids = list(existing.media_ids or []) if existing else []
    media_ids, media, primary_url, primary_plan = await _media_for_new_draft(
        db,
        session,
        image_url=state.get("image_url") or (existing.image_url if existing else None),
        image_plan=state.get("image_plan")
        if isinstance(state.get("image_plan"), dict)
        else (existing.image_plan if existing else None),
        image_format=None,
        reuse_media_ids=reuse_ids,
        create_image_row=False,
    )
    if not media_ids and (primary_url or primary_plan):
        media_ids, media, primary_url, primary_plan = await _backfill_primary_image_row(
            db, session, primary_url=primary_url, primary_plan=primary_plan
        )
    return await _bump_preview_revision(
        db,
        session,
        media_ids=media_ids,
        media=media,
        primary_url=primary_url,
        primary_plan=primary_plan if isinstance(primary_plan, dict) else None,
        copy=copy,
    )


async def _bump_preview_revision(
    db: AsyncSession,
    session: Session,
    *,
    media_ids: list[uuid.UUID],
    media: list[dict[str, Any]],
    primary_url: str | None,
    primary_plan: dict[str, Any] | None,
    copy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a new preview_drafts row + sync session.state / SSE (ADR 0008)."""
    if session.status == "confirmed":
        raise ValueError("Session already confirmed")

    state = dict(session.state or {})
    existing = await repos.get_latest_preview_draft(db, session.id)
    draft_copy = normalize_draft_copy(
        copy if copy is not None else (existing.copy if existing else state.get("draft"))
    )
    if not draft_copy["caption"].strip():
        raise ValueError("caption is required")

    base_rev = existing.revision if existing else int(state.get("revision") or 0)
    rev = base_rev + 1
    token = secrets.token_urlsafe(24)
    source_signal_ids = list(state.get("source_signal_ids") or [])
    if existing and existing.source_signal_ids and not source_signal_ids:
        source_signal_ids = list(existing.source_signal_ids)
    platform = (existing.platform if existing else None) or DEFAULT_PLATFORM

    await repos.upsert_preview_draft(
        db,
        session_id=session.id,
        revision=rev,
        copy=draft_copy,
        image_url=primary_url,
        image_plan=primary_plan,
        media_ids=media_ids,
        source_signal_ids=source_signal_ids,
        approval_token=token,
        platform=platform,
    )

    state["draft"] = draft_copy
    state["revision"] = rev
    state["approval_token"] = token
    state["image_url"] = primary_url
    image_format = image_format_from_plan(
        primary_plan, fallback=str(state.get("image_format") or "single")
    )
    if primary_plan is not None:
        state["image_plan"] = primary_plan
        state["image_format"] = image_format
    state["media_ids"] = [str(i) for i in media_ids]
    state["pending_confirm"] = False
    state["need_image"] = False
    state["awaiting_image_ok"] = False
    state.pop("turn_discard", None)
    session.state = state
    session.mode = MODE_PREVIEW

    graph = get_session_graph()
    config = graph_state._session_config(session.id)
    graph_update: dict[str, Any] = {
        "draft": draft_copy,
        "revision": rev,
        "approval_token": token,
        "image_url": primary_url,
        "image_plan": primary_plan or {},
        "mode": MODE_PREVIEW,
        "pending_confirm": False,
        "need_image": False,
    }
    if primary_plan is not None:
        graph_update["image_format"] = image_format
    try:
        await graph.aupdate_state(
            config,
            graph_update,
        )
    except Exception:
        logger.warning(
            "Failed to sync graph checkpoint after preview revision (session=%s)",
            session.id,
            exc_info=True,
        )

    resolved_signals = await resolve_source_signals(db, source_signal_ids)
    events = [
        {"type": "draft.copy_updated", "data": draft_copy},
        {
            "type": "preview.updated",
            "data": preview_updated_payload(
                revision=rev,
                approval_token=token,
                image_url=primary_url,
                copy=draft_copy,
                platform=platform,
                media=media,
                source_signals=resolved_signals,
            ),
        },
    ]
    await db.flush()
    await session_event_bus.publish_many(session.id, events)
    return {
        "revision": rev,
        "approval_token": token,
        "copy": draft_copy,
        "image_url": resolve_stored_url(primary_url),
        "media": media,
        "platform": platform,
        "mode": MODE_PREVIEW,
        "source_signals": resolved_signals,
        "events": events,
    }
