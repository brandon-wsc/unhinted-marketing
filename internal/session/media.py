"""Preview media helpers (ADR 0008) — pure bits for dual-write / hydrate."""

from __future__ import annotations

import uuid
from typing import Any


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
        "url": url,
        "plan": dict(plan or {}),
        "format": format,
        "role": role,
        "seq": seq,
        "status": status,
    }
