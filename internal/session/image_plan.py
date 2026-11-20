"""Pending image script+plan staging and session image mutations for session routes and turns."""

from __future__ import annotations

import secrets
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from internal.llm.resolve import company_llm_scope
from internal.llm.router import LlmProviderError
from internal.media.storage import resolve_stored_url, sniff_image_bytes
from internal.memory import repos
from internal.memory.models import (
    Session,
)
from internal.session import graph_state, previews
from internal.session.events import session_event_bus
from internal.session.graph import (
    get_session_graph,
)
from internal.session.image_format import adapt_plan_to_format, plan_direction_changed
from internal.session.media import image_format_from_plan
from internal.session.state import MODE_PREVIEW
from internal.session.turn_registry import (
    session_turn_registry,
)


def _replace_media_id(
    media_ids: list[uuid.UUID], old_id: uuid.UUID, new_id: uuid.UUID
) -> list[uuid.UUID]:
    return [new_id if i == old_id else i for i in media_ids]


def _fallback_direction_copy(
    draft: dict[str, Any], plan: dict[str, Any], note: str
) -> dict[str, Any]:
    """Offline script so a direction change is visible without an LLM (ADR 0036)."""
    base = str(draft.get("caption") or "").strip()
    fmt = image_format_from_plan(plan, fallback="single")
    vehicle = "4格漫畫" if fmt == "comic_4panel" else "單圖"
    detail = (note or str(plan.get("prompt") or "")).strip()
    line = f"（{vehicle}：{detail[:180]}）"
    caption = base if line and line in base else f"{base}\n\n{line}".strip()
    return previews.normalize_draft_copy(
        {
            "caption": caption or line or "（修訂草稿）",
            "hashtags": draft.get("hashtags") or [],
            "cta": draft.get("cta") or "",
        }
    )


async def _rewrite_copy_for_direction(
    db: AsyncSession,
    session: Session,
    *,
    draft: dict[str, Any],
    plan: dict[str, Any],
    note: str,
) -> dict[str, Any]:
    """New caption that matches the pending image plan. Fallback keeps tests offline."""
    from internal.llm.router import has_llm_credentials

    if has_llm_credentials():
        import json

        from internal.session import execute_harness as EH

        payload = {
            "draft": draft,
            "user_feedback": note,
            "reviewer_feedback": "",
            "voice_pack": (session.state or {}).get("voice_pack") or {},
            "signals": [],
            "allowed_signal_ids": [],
            "image_format": image_format_from_plan(plan, fallback="single"),
            "image_plan": plan,
        }
        async with company_llm_scope(db, session.company_id):
            parsed = await EH.run_edit_copy_agent(
                json.dumps(payload, ensure_ascii=False),
            )
        if parsed and str(parsed.caption or "").strip():
            return previews.normalize_draft_copy(
                {
                    "caption": parsed.caption,
                    "hashtags": parsed.hashtags,
                    "cta": parsed.cta,
                }
            )
    return _fallback_direction_copy(draft, plan, note)


def _apply_pending_image_state(
    session: Session,
    staged: dict[str, Any],
    *,
    pre_state: dict[str, Any],
    pre_mode: str,
) -> None:
    """Hydrate session.state for a pending Execute card (ADR 0036)."""
    state = dict(session.state or {})
    if not isinstance(state.get("turn_discard"), dict):
        state["turn_discard"] = {
            "pre_state": graph_state._strip_discard_meta(pre_state),
            "pre_mode": pre_mode,
            "message_ids": [],
            "accepted_revision": int(pre_state.get("revision") or 0),
        }
    state["draft"] = staged["copy"]
    state["revision"] = staged["revision"]
    state["approval_token"] = staged["approval_token"]
    state["image_plan"] = staged["image_plan"]
    state["image_format"] = staged["image_format"]
    state["image_url"] = staged["image_url"]
    state["need_image"] = True
    state["awaiting_image_ok"] = True
    state["pending_confirm"] = False
    session.state = state
    session.mode = MODE_PREVIEW


async def _stage_pending_image_draft(
    db: AsyncSession,
    session: Session,
    *,
    copy: dict[str, Any],
    image_plan: dict[str, Any],
    source_signal_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    """Insert caption + plan on a new preview revision and park before image gen.

    Returns None when the latest row already matches (resume re-park).
    """
    draft_copy = previews.normalize_draft_copy(copy)
    if not draft_copy["caption"].strip():
        return None
    fmt = image_format_from_plan(
        image_plan, fallback=str((session.state or {}).get("image_format") or "single")
    )
    plan = adapt_plan_to_format(dict(image_plan), fmt)
    fmt = image_format_from_plan(plan, fallback=fmt)

    existing = await repos.get_latest_preview_draft(db, session.id)
    if existing is not None:
        same_copy = previews.normalize_draft_copy(existing.copy) == draft_copy
        same_plan = dict(existing.image_plan or {}) == dict(plan)
        if same_copy and same_plan:
            return None

    state = dict(session.state or {})
    base_rev = existing.revision if existing else int(state.get("revision") or 0)
    rev = base_rev + 1
    token = secrets.token_urlsafe(24)
    signal_ids = list(
        source_signal_ids
        if source_signal_ids is not None
        else (state.get("source_signal_ids") or [])
    )
    if existing and existing.source_signal_ids and not signal_ids:
        signal_ids = list(existing.source_signal_ids)
    platform = (existing.platform if existing else None) or previews.DEFAULT_PLATFORM

    old_ids = list(existing.media_ids or []) if existing else []
    row = await repos.insert_preview_image(
        db,
        session_id=session.id,
        url=None,
        plan=plan,
        format=fmt,
        role="primary",
        seq=0,
        status="pending",
    )
    media_ids = [row.id, *old_ids[1:]]
    rows = await repos.get_preview_images_by_ids(db, media_ids)
    media, primary_url, primary_plan = previews._payloads_from_image_rows(rows)
    stored_plan = primary_plan or plan

    await repos.upsert_preview_draft(
        db,
        session_id=session.id,
        revision=rev,
        copy=draft_copy,
        image_url=primary_url,
        image_plan=stored_plan,
        media_ids=media_ids,
        source_signal_ids=signal_ids,
        approval_token=token,
        platform=platform,
    )

    graph = get_session_graph()
    config = graph_state._session_config(session.id)
    msgs = await repos.list_session_messages(db, session.id)
    message_dicts = [{"role": m.role, "content": m.content} for m in msgs]
    graph_values = graph_state._graph_values(session, message_dicts)
    graph_values.update(
        {
            "draft": draft_copy,
            "image_plan": stored_plan,
            "image_format": fmt,
            "image_url": primary_url,
            "revision": rev,
            "approval_token": token,
            "mode": MODE_PREVIEW,
            "need_image": True,
            "reviewer_passed": True,
            "pending_confirm": False,
        }
    )
    await graph.aupdate_state(config, graph_values, as_node="executor_image_plan")

    return {
        "revision": rev,
        "approval_token": token,
        "copy": draft_copy,
        "image_url": resolve_stored_url(primary_url),
        "image_plan": stored_plan,
        "image_format": fmt,
        "media": media,
        "platform": platform,
        "mode": MODE_PREVIEW,
        "source_signals": await previews.resolve_source_signals(db, signal_ids),
    }


async def update_session_image_plan(
    db: AsyncSession,
    session: Session,
    *,
    image_id: uuid.UUID,
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Edit plan. A direction/format change stages a new script and parks for Execute."""
    if session.mode != MODE_PREVIEW:
        raise ValueError("Session is not in PREVIEW mode")
    if session_turn_registry.is_busy(session.id):
        raise ValueError("Session turn already in progress")
    existing = await repos.get_latest_preview_draft(db, session.id)
    if not existing:
        raise ValueError("No preview draft yet")
    media_ids = list(existing.media_ids or [])
    if image_id not in media_ids:
        raise ValueError("Image is not part of the current draft")
    old = await repos.get_preview_image(db, image_id)
    if old is None or old.session_id != session.id:
        raise ValueError("Image not found")

    fmt = image_format_from_plan(plan, fallback=old.format)
    old_fmt = image_format_from_plan(old.plan, fallback=old.format)
    new_plan = adapt_plan_to_format(dict(plan), fmt, previous_format=old_fmt)
    fmt = image_format_from_plan(new_plan, fallback=fmt)
    if plan_direction_changed(dict(old.plan or {}), new_plan):
        current_copy = previews.normalize_draft_copy(existing.copy or (session.state or {}).get("draft"))
        note = (
            f"創作方向變咗。新圖格式係 {fmt}。"
            f"畫面：{str(new_plan.get('prompt') or '')[:300]}。"
            "請改寫 caption、hashtags、cta 去配合呢個畫面同格式。"
        )
        copy = await _rewrite_copy_for_direction(
            db, session, draft=current_copy, plan=new_plan, note=note
        )
        pre_state = graph_state._strip_discard_meta(session.state)
        pre_mode = session.mode
        anchor = (session.state or {}).get("turn_discard")
        if isinstance(anchor, dict) and isinstance(anchor.get("pre_state"), dict):
            pre_state = graph_state._strip_discard_meta(anchor["pre_state"])
            if isinstance(anchor.get("pre_mode"), str):
                pre_mode = anchor["pre_mode"]
        staged = await _stage_pending_image_draft(
            db,
            session,
            copy=copy,
            image_plan=new_plan,
            source_signal_ids=list(existing.source_signal_ids or []),
        )
        if staged is None:
            raise ValueError("Could not stage the new image version")
        _apply_pending_image_state(session, staged, pre_state=pre_state, pre_mode=pre_mode)
        events = [
            {"type": "draft.copy_updated", "data": staged["copy"]},
            {
                "type": "preview.updated",
                "data": previews.preview_updated_payload(
                    revision=int(staged["revision"]),
                    approval_token=str(staged["approval_token"]),
                    image_url=staged.get("image_url"),
                    copy=staged["copy"],
                    platform=staged.get("platform"),
                    media=staged.get("media") or [],
                    source_signals=staged.get("source_signals"),
                ),
            },
            {"type": "draft.awaiting_image_ok", "data": {"awaiting": True}},
        ]
        await session_event_bus.publish_many(session.id, events)
        return {**staged, "awaiting_image_ok": True, "events": events}

    row = await repos.insert_preview_image(
        db,
        session_id=session.id,
        url=old.url,
        plan=new_plan,
        format=fmt,
        role=old.role,
        seq=old.seq,
        status=old.status if old.url else "pending",
    )
    new_ids = _replace_media_id(media_ids, image_id, row.id)
    rows = await repos.get_preview_images_by_ids(db, new_ids)
    media, primary_url, primary_plan = previews._payloads_from_image_rows(rows)
    return await previews._bump_preview_revision(
        db,
        session,
        media_ids=new_ids,
        media=media,
        primary_url=primary_url,
        primary_plan=primary_plan,
    )


async def regen_session_image(
    db: AsyncSession,
    session: Session,
    *,
    image_id: uuid.UUID,
) -> dict[str, Any]:
    """Re-sample the current locked plan. Refuses a pending direction change."""
    from internal.llm.router import (
        generate_image,
        has_llm_credentials,
        resolve_image_model,
    )
    from internal.media.storage import media_object_key, persist_generated_image
    from internal.session.image_format import compose_generation_prompt

    if session.mode != MODE_PREVIEW:
        raise ValueError("Session is not in PREVIEW mode")
    if (session.state or {}).get("awaiting_image_ok"):
        raise ValueError(
            "This version is waiting to generate. Execute or discard before resampling."
        )
    existing = await repos.get_latest_preview_draft(db, session.id)
    if not existing:
        raise ValueError("No preview draft yet")
    media_ids = list(existing.media_ids or [])
    if image_id not in media_ids:
        raise ValueError("Image is not part of the current draft")
    old = await repos.get_preview_image(db, image_id)
    if old is None or old.session_id != session.id:
        raise ValueError("Image not found")

    # Same locked plan only — do not rewrite format or prompt (ADR 0036).
    plan = dict(old.plan or {})
    fmt = image_format_from_plan(plan, fallback=old.format)
    plan["format"] = fmt
    prompt = compose_generation_prompt(plan)
    if not prompt:
        prompt = f"Clean modern social media image for Hong Kong brand, format={fmt}"

    async with company_llm_scope(db, session.company_id):
        image_model = resolve_image_model()
        if not has_llm_credentials() or (image_model and image_model.lower() == "placeholder"):
            url = f"placeholder://local/{session.id}/regen-{secrets.token_hex(4)}.png"
        elif not image_model:
            raise LlmProviderError(
                "No image model configured (set LLM_IMAGE_MODEL).",
                kind="unsupported",
            )
        else:
            raw_ref = await generate_image(prompt=prompt)
            rev = (existing.revision if existing else 0) + 1
            key = media_object_key(session_id=str(session.id), revision=rev)
            url = await persist_generated_image(raw_ref, key=key)

    row = await repos.insert_preview_image(
        db,
        session_id=session.id,
        url=url,
        plan=plan,
        format=fmt,
        role=old.role,
        seq=old.seq,
        status="ready",
    )
    new_ids = _replace_media_id(media_ids, image_id, row.id)
    rows = await repos.get_preview_images_by_ids(db, new_ids)
    media, primary_url, primary_plan = previews._payloads_from_image_rows(rows)
    return await previews._bump_preview_revision(
        db,
        session,
        media_ids=new_ids,
        media=media,
        primary_url=primary_url,
        primary_plan=primary_plan,
    )


async def add_session_image(
    db: AsyncSession,
    session: Session,
    *,
    format: str = "single",
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a new image slot (pending plan) → new image row + new draft."""
    if session.mode != MODE_PREVIEW:
        raise ValueError("Session is not in PREVIEW mode")
    existing = await repos.get_latest_preview_draft(db, session.id)
    if not existing:
        raise ValueError("No preview draft yet")
    media_ids = list(existing.media_ids or [])
    fmt = image_format_from_plan(plan, fallback=format)
    new_plan = adapt_plan_to_format(dict(plan or {}), fmt)
    fmt = image_format_from_plan(new_plan, fallback=fmt)
    seq = len(media_ids)
    row = await repos.insert_preview_image(
        db,
        session_id=session.id,
        url=None,
        plan=new_plan,
        format=fmt,
        role="primary" if seq == 0 else "extra",
        seq=seq,
        status="pending",
    )
    new_ids = [*media_ids, row.id]
    rows = await repos.get_preview_images_by_ids(db, new_ids)
    media, primary_url, primary_plan = previews._payloads_from_image_rows(rows)
    return await previews._bump_preview_revision(
        db,
        session,
        media_ids=new_ids,
        media=media,
        primary_url=primary_url,
        primary_plan=primary_plan,
    )


_UPLOAD_MAX_BYTES = 10 * 1024 * 1024


async def remove_session_image(
    db: AsyncSession,
    session: Session,
    *,
    image_id: uuid.UUID,
) -> dict[str, Any]:
    """Remove image id from current draft media_ids → new draft (orphan row OK)."""
    if session.mode != MODE_PREVIEW:
        raise ValueError("Session is not in PREVIEW mode")
    existing = await repos.get_latest_preview_draft(db, session.id)
    if not existing:
        raise ValueError("No preview draft yet")
    media_ids = list(existing.media_ids or [])
    if image_id not in media_ids:
        raise ValueError("Image is not part of the current draft")
    if len(media_ids) <= 1:
        raise ValueError("Cannot remove the last remaining image")
    new_ids = [i for i in media_ids if i != image_id]
    rows = await repos.get_preview_images_by_ids(db, new_ids)
    media, primary_url, primary_plan = previews._payloads_from_image_rows(rows)
    return await previews._bump_preview_revision(
        db,
        session,
        media_ids=new_ids,
        media=media,
        primary_url=primary_url,
        primary_plan=primary_plan,
    )


async def upload_session_image(
    db: AsyncSession,
    session: Session,
    *,
    image_id: uuid.UUID,
    data: bytes,
    content_type: str,
) -> dict[str, Any]:
    """Upload user image → new preview_images row + replace slot in draft."""
    from internal.media.storage import MediaStorageError, media_object_key, put_bytes

    if session.mode != MODE_PREVIEW:
        raise ValueError("Session is not in PREVIEW mode")
    existing = await repos.get_latest_preview_draft(db, session.id)
    if not existing:
        raise ValueError("No preview draft yet")
    media_ids = list(existing.media_ids or [])
    if image_id not in media_ids:
        raise ValueError("Image is not part of the current draft")
    old = await repos.get_preview_image(db, image_id)
    if old is None or old.session_id != session.id:
        raise ValueError("Image not found")

    if not data:
        raise ValueError("Empty upload")
    if len(data) > _UPLOAD_MAX_BYTES:
        raise ValueError("Image too large (max 10MB)")
    sniffed = sniff_image_bytes(data)
    if not sniffed:
        raise ValueError("File must be an image (jpeg, png, webp, or gif)")
    ct, ext = sniffed

    plan = dict(old.plan or {})
    fmt = image_format_from_plan(plan, fallback=old.format)
    plan["format"] = fmt

    rev = (existing.revision if existing else 0) + 1
    key = media_object_key(session_id=str(session.id), revision=rev, ext=ext)
    try:
        await put_bytes(key=key, data=data, content_type=ct)
    except MediaStorageError as exc:
        raise MediaStorageError(str(exc)) from exc

    row = await repos.insert_preview_image(
        db,
        session_id=session.id,
        url=key,
        plan=plan,
        format=fmt,
        role=old.role,
        seq=old.seq,
        status="ready",
    )
    new_ids = _replace_media_id(media_ids, image_id, row.id)
    rows = await repos.get_preview_images_by_ids(db, new_ids)
    media, primary_url, primary_plan = previews._payloads_from_image_rows(rows)
    return await previews._bump_preview_revision(
        db,
        session,
        media_ids=new_ids,
        media=media,
        primary_url=primary_url,
        primary_plan=primary_plan,
    )
