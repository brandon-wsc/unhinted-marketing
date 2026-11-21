"""Image-plan tool body for the main agent — ADR 0062.

``run_plan_image`` folds the legacy ``executor_image_plan`` vertex into one
tool call: the ImagePlanOut inner call, deterministic avoid-merge and format
normalization, plus the same fallback plan the vertex wrote. Generation and
the human Execute park stay outer — the agent only writes the script+plan,
and the node routes a written plan to ``executor_image_gen``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel

from internal.session import harness as H
from internal.session import prompts
from internal.session.image_format import (
    COMIC_COMPOSITION,
    COMIC_STYLE,
    DEFAULT_COMIC_PANELS,
    SINGLE_COMPOSITION,
    SINGLE_STYLE,
    default_avoid,
    merge_default_avoid,
    normalize_image_format,
)
from internal.session.io import ImagePlanOut

logger = logging.getLogger(__name__)

_plan_override: BaseChatModel | None = None


def set_plan_model_override(model: BaseChatModel | None) -> None:
    """Test hook: inject a scripted chat model. Pass None to restore live."""
    global _plan_override
    _plan_override = model


@dataclass
class PlanImageResult:
    reply: str  # JSON string the tool returns to the main agent
    state_update: dict[str, Any] = field(default_factory=dict)


def _fallback_plan(company: dict[str, Any], draft: dict[str, Any], fmt: str) -> dict[str, Any]:
    """Deterministic plan — same shape the vertex wrote on a parse miss."""
    company_name = company.get("name") or "brand"
    seed = str(draft.get("caption") or "")[:120] or "market trends"
    if fmt == "comic_4panel":
        return {
            "format": "comic_4panel",
            "prompt": (
                f"4-panel clean-line comic strip for {company_name}, Hong Kong everyday scenes "
                f"inspired by: {seed}, clear gutters, natural daylight, "
                "in panel 4 a character holds the product in hand, "
                "no logos, no unreadable text"
            ),
            "composition": COMIC_COMPOSITION,
            "style": COMIC_STYLE,
            "avoid": default_avoid(COMIC_STYLE),
            "panels": [dict(p) for p in DEFAULT_COMIC_PANELS],
        }
    return {
        "format": "single",
        "prompt": (
            f"Clean-line contemporary Hong Kong comic illustration for {company_name}, "
            f"single vertical 4:5 panel, inspired by: {seed}, "
            "a character clearly holds the product in hand, natural daylight, "
            "flat natural colors, no logos, no unreadable text"
        ),
        "composition": SINGLE_COMPOSITION,
        "style": SINGLE_STYLE,
        "avoid": default_avoid(SINGLE_STYLE),
        "panels": [],
    }


async def run_plan_image(payload: dict[str, Any]) -> PlanImageResult:
    """Port of ``executor_image_plan`` — writes ``image_plan`` + ``image_format``."""
    fmt = normalize_image_format(payload.get("image_format"))
    draft = payload.get("draft") or {}
    company = payload.get("company") or payload.get("company_context") or {}
    plan_payload = {
        "draft": draft,
        "brief": payload.get("brief") or {},
        "company": company,
        "voice_pack": {
            k: v
            for k, v in (payload.get("voice_pack") or {}).items()
            if k in ("roast_level", "locale")
        },
        "image_format": fmt,
    }
    parsed = await H.run_typed(
        "executor_image_plan",
        prompts.IMAGE_PLAN,
        json.dumps(plan_payload, ensure_ascii=False),
        ImagePlanOut,
        _plan_override,
    )
    if parsed:
        plan = merge_default_avoid(parsed.model_dump())
        plan["format"] = normalize_image_format(plan.get("format") or fmt)
        if plan["format"] != "comic_4panel":
            plan["panels"] = []
    else:
        plan = _fallback_plan(company, draft, fmt)

    update = {"image_plan": plan, "image_format": plan["format"]}
    reply = json.dumps(
        {"planned": True, "format": plan["format"]}, ensure_ascii=False
    )
    return PlanImageResult(reply=reply, state_update=update)
