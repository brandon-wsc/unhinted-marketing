"""Preview media helpers (ADR 0008 / 0025) — dual-write / hydrate."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from internal.media.storage import resolve_stored_url


def image_format_from_plan(plan: dict[str, Any] | None, fallback: str = "single") -> str:
    if not plan:
        return fallback
    raw = plan.get("format")
    if raw in ("single", "comic_4panel"):
        return str(raw)
    return fallback


def media_item_payload(
    *,
    image_id: uuid.UUID,
    url: str | None,
    plan: dict[str, Any] | None,
    format: str,
    role: str = "primary",
    seq: int = 0,
    status: str = "ready",
) -> dict[str, Any]:
    return {
        "id": str(image_id),
        "url": resolve_stored_url(url),
        "plan": dict(plan or {}),
        "format": format,
        "role": role,
        "seq": seq,
        "status": status,
    }


def media_bundle_from_rows(
    rows: Sequence[Any],
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any] | None]:
    """Client media[] plus the stored primary ref (key or external URL)."""
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
    stored = rows[0].url if rows else None
    plan = dict(rows[0].plan or {}) if rows else None
    return media, stored, plan
