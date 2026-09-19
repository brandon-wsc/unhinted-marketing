"""Visual format for executor_image_plan / gen — single image or 4-panel comic strip."""

from __future__ import annotations

import re
from typing import Any, Literal

ImageFormat = Literal["single", "comic_4panel"]
DEFAULT_IMAGE_FORMAT: ImageFormat = "single"
IMAGE_FORMAT_OPTIONS: tuple[ImageFormat, ...] = ("single", "comic_4panel")
_VALID: frozenset[str] = frozenset(IMAGE_FORMAT_OPTIONS)

# Brief can_do / cannot_do lines that pick a vehicle (not tone).
_FORMAT_CONSTRAINT = re.compile(
    r"(格式|漫畫分格|4\s*格漫畫|四格漫畫|comic_4panel|單圖|"
    r"carousel|4-panel|four-panel|唔需要漫畫)",
    re.I,
)
_LOCK_CAN_DO: dict[ImageFormat, str] = {
    "comic_4panel": (
        "格式鎖定 4 格漫畫：每個 angle 用起、承、轉、合四格節奏寫；"
        "第 1 格一秒出畫面，第 4 格先圓回品牌。語氣／抽水可改，格式唔改。"
    ),
    "single": "格式鎖定單圖：一張主視覺 + caption；語氣／抽水可改，格式唔改做漫畫。",
}
_LOCK_CANNOT_DO: dict[ImageFormat, str] = {
    "comic_4panel": (
        "唔可以因為想溫柔／少抽水／改語氣而將已鎖定嘅 4 格漫畫"
        "改做單圖、生活照、長圖拼貼或 6–8 格"
    ),
    "single": "唔可以將已鎖定嘅單圖改做 4 格漫畫",
}


def normalize_image_format(raw: Any) -> ImageFormat:
    if isinstance(raw, str) and raw.strip() in _VALID:
        return raw.strip()  # type: ignore[return-value]
    return DEFAULT_IMAGE_FORMAT


def lock_brief_to_format(brief: dict[str, Any], fmt: Any) -> dict[str, Any]:
    """Replace vehicle lines so a sticky pick cannot be rewritten as 單圖/漫畫."""
    locked = normalize_image_format(fmt)
    out = dict(brief)

    def _keep(lines: Any) -> list[str]:
        if not isinstance(lines, list):
            return []
        kept: list[str] = []
        for line in lines:
            if not isinstance(line, str):
                continue
            if _FORMAT_CONSTRAINT.search(line):
                continue
            kept.append(line)
        return kept

    out["can_do"] = [_LOCK_CAN_DO[locked], *_keep(out.get("can_do"))]
    out["cannot_do"] = [_LOCK_CANNOT_DO[locked], *_keep(out.get("cannot_do"))]
    return out


def image_format_from_text(text: str) -> ImageFormat | None:
    """Detect explicit user request for comic strip; None = leave default."""
    lower = text.lower()
    if any(k in text for k in ("4格", "四格", "四格漫畫", "4格漫畫")):
        return "comic_4panel"
    if any(k in lower for k in ("comic strip", "4-panel", "four panel", "four-panel")):
        return "comic_4panel"
    if any(k in text for k in ("單圖", "普通圖", "一張圖")) or "single image" in lower:
        return "single"
    return None


def compose_generation_prompt(plan: dict[str, Any]) -> str:
    """Build the string passed to the image model (one image either way)."""
    fmt = normalize_image_format(plan.get("format"))
    base = str(plan.get("prompt") or "").strip()
    composition = str(plan.get("composition") or "").strip()
    style = str(plan.get("style") or "").strip()
    avoid = plan.get("avoid") or []
    avoid_s = ", ".join(str(a) for a in avoid if a) if isinstance(avoid, list) else ""

    parts: list[str] = []
    if fmt == "comic_4panel":
        parts.append(
            "Create ONE image that is a 4-panel comic strip (2x2 or horizontal), "
            "clear gutters, left-to-right then top-to-bottom reading order, "
            "Hong Kong everyday mood. Story arc: panels 1-3 build situational empathy "
            "and unnamed pain with NO product; panel 4 only soft-introduces the product "
            "as a remedy (native integration, no feature list, minimal/no readable text)."
        )
        panels = plan.get("panels") or []
        if isinstance(panels, list) and panels:
            beats: list[str] = []
            for p in panels[:4]:
                if isinstance(p, dict):
                    idx = p.get("index", len(beats) + 1)
                    beat = str(p.get("beat") or "").strip()
                    if beat:
                        beats.append(f"Panel {idx}: {beat}")
            if beats:
                parts.append("Panel beats: " + " | ".join(beats))
    if base:
        parts.append(base)
    if composition:
        parts.append(f"Composition: {composition}")
    if style:
        parts.append(f"Style: {style}")
    if avoid_s:
        parts.append(f"Avoid: {avoid_s}")
    return " ".join(parts).strip()
