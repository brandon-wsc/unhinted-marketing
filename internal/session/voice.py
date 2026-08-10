"""HK social craft helpers — see docs/VOICE.md and docs/knowledge/MODEL.md."""

from __future__ import annotations

from typing import Any

# Default when company.profile.roast_level is missing or invalid.
DEFAULT_ROAST_LEVEL = 1
MAX_ROAST_LEVEL = 3
DEFAULT_LOCALE = "zh-HK"
MAX_FORBIDDEN_PHRASES = 15
MAX_EXEMPLAR_CAPTIONS = 3
MAX_EXEMPLAR_CHARS = 150

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


def normalize_exemplar_captions(raw: Any) -> list[str]:
    """≤3 captions × ≤150 chars; drop empties; preserve order."""
    if not isinstance(raw, list):
        return []
    caps: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        cap = item.strip()[:MAX_EXEMPLAR_CHARS]
        if not cap or cap in seen:
            continue
        seen.add(cap)
        caps.append(cap)
        if len(caps) >= MAX_EXEMPLAR_CAPTIONS:
            break
    return caps


def prepend_exemplar_caption(existing: list[str] | Any, caption: str) -> list[str]:
    """Promote a draft caption to the front of the exemplar list (K5)."""
    base = normalize_exemplar_captions(existing)
    cap = caption.strip()[:MAX_EXEMPLAR_CHARS] if isinstance(caption, str) else ""
    if not cap:
        return base
    return normalize_exemplar_captions([cap, *base])


def voice_pack(profile: dict[str, Any] | None) -> dict[str, Any]:
    """Compressed brand voice for LLM payloads (MODEL voice_pack)."""
    profile = dict(profile or {})
    level = roast_level_from_profile(profile)
    locale_raw = profile.get("locale")
    locale = (
        locale_raw.strip()
        if isinstance(locale_raw, str) and locale_raw.strip()
        else DEFAULT_LOCALE
    )
    out: dict[str, Any] = {
        "craft": "hk_social_editor",
        "roast_level": level,
        "roast_level_label": ROAST_LEVEL_LABELS[level],
        "locale": locale,
    }

    phrases = profile.get("forbidden_phrases") or []
    if isinstance(phrases, list):
        cleaned = [str(p).strip() for p in phrases if str(p).strip()][:MAX_FORBIDDEN_PHRASES]
        if cleaned:
            out["forbidden_phrases"] = cleaned

    tone = profile.get("tone_notes")
    if isinstance(tone, str) and tone.strip():
        out["tone_notes"] = tone.strip()

    caps = normalize_exemplar_captions(profile.get("exemplar_captions"))
    if caps:
        out["exemplar_captions"] = caps

    return out


def voice_context(profile: dict[str, Any] | None) -> dict[str, Any]:
    """Alias for voice_pack (legacy call sites)."""
    return voice_pack(profile)


def audience_catalog_entry(
    *,
    slug: str,
    name: str | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, str]:
    """One compressed audience row for session (MODEL audience_catalog)."""
    profile = dict(profile or {})
    label = str(profile.get("label") or name or slug).strip() or slug
    hook = profile.get("hook")
    if not isinstance(hook, str) or not hook.strip():
        prefs = profile.get("content_preferences") or []
        if isinstance(prefs, list) and prefs:
            hook = str(prefs[0]).strip()
        else:
            desc = profile.get("description")
            hook = str(desc).strip() if isinstance(desc, str) else ""
    if not hook:
        hook = "HK audience"
    return {"slug": slug, "label": label, "hook": hook[:160]}


def audience_catalog_from_entities(personas: list[Any]) -> list[dict[str, str]]:
    """Compress persona entities → audience_catalog (no raw profile dump)."""
    out: list[dict[str, str]] = []
    for persona in personas:
        slug = getattr(persona, "slug", None) or ""
        if not slug:
            continue
        out.append(
            audience_catalog_entry(
                slug=slug,
                name=getattr(persona, "name", None),
                profile=getattr(persona, "profile", None),
            )
        )
    return out


def pick_active_persona(
    catalog: list[dict[str, str]],
    persona_slug: str | None,
) -> dict[str, str] | None:
    if not catalog:
        return None
    if persona_slug:
        for row in catalog:
            if row.get("slug") == persona_slug:
                return row
    return catalog[0]
