"""HK social craft helpers — see docs/VOICE.md."""

from __future__ import annotations

from typing import Any

# Default when company.profile.roast_level is missing or invalid.
DEFAULT_ROAST_LEVEL = 1
MAX_ROAST_LEVEL = 3

ROAST_LEVEL_LABELS: dict[int, str] = {
    0: "穩陣 — clear benefit, soft CTA, light humour only",
    1: "輕鬆小編 — warm zh-HK spoken, scene hook, mild wit (default)",
    2: "港式抽水 — trend parody / local punchline; product still lands",
    3: "抽水王 — max meme energy; grounded; no cruelty or fake news",
}


def normalize_roast_level(raw: Any) -> int:
    try:
        level = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_ROAST_LEVEL
    return max(0, min(MAX_ROAST_LEVEL, level))


def roast_level_from_profile(profile: dict[str, Any] | None) -> int:
    if not profile:
        return DEFAULT_ROAST_LEVEL
    return normalize_roast_level(profile.get("roast_level"))


def voice_context(profile: dict[str, Any] | None) -> dict[str, Any]:
    """Slice of company profile for LLM payloads (always includes roast_level)."""
    profile = dict(profile or {})
    level = roast_level_from_profile(profile)
    out: dict[str, Any] = {
        "roast_level": level,
        "roast_level_label": ROAST_LEVEL_LABELS[level],
        "craft": "hk_social_editor",
    }
    for key in ("locale", "tone_notes", "forbidden_phrases"):
        if key in profile and profile[key] not in (None, "", []):
            out[key] = profile[key]
    return out
