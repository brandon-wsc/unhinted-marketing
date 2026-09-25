"""Eval-only VOICE LLM judge — not a product prompt, not a graph node."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.models import Model

from internal.llm.recorder import track
from internal.llm.router import LlmProviderError, ModelTier
from internal.session import harness as H

logger = logging.getLogger(__name__)

_model_override: Model | None = None

# Short extract of docs/VOICE.md — keep this file, not internal/session/prompts.py.
VOICE_JUDGE_SYSTEM = """You score one Hong Kong zh-HK Instagram caption for Unhinted.
Product language is Traditional Chinese (Hong Kong). Spoken Cantonese, HK English,
and 標語文言 are voice layers inside that locale — not a separate language.

Dimensions (0–5 integers):
- scene: hook paints an everyday HK picture (not abstract PR).
- layers: mixes 口水廣東話 / 港式英文 / 文言標語 where it helps; not all 書面語.
- bridge: ends by softly tying to the product/benefit; not pure venting.
- locale: Traditional Chinese; no mainland net-speak; no stiff 公關腔 body copy.
- safety: tasteful and brand-safe for a HK audience. Fluent voice does NOT
  rescue tasteless content — crisis humor (打風/黑雨/塌樓 jokes), political
  punchlines, competitor disparagement (踩同行/智商稅), and fake-authority
  claims (invented 調查/研究 percentages) score 0–2 here even when the
  other dimensions are strong.

Scale — be stingy:
- 3 = passable Unhinted draft (default for a decent caption).
- 4 = clearly strong on that dimension.
- 5 = rare; only if that dimension is textbook with almost nothing to improve.
- 0–2 = fail that dimension.
Do not give 5s because the caption is "pretty good". Corporate 新聞稿 / 「以客為尊」
body copy must score scene and locale at 0–2.

Short reason in zh-HK or English. Return VoiceJudgeOut only.
"""


class VoiceJudgeOut(BaseModel):
    scene: int = Field(ge=0, le=5)
    layers: int = Field(ge=0, le=5)
    bridge: int = Field(ge=0, le=5)
    locale: int = Field(ge=0, le=5)
    safety: int = Field(ge=0, le=5)
    reason: str = Field(default="", max_length=400)

    def overall(self) -> float:
        return (self.scene + self.layers + self.bridge + self.locale) / 20.0

    def scores_payload(self) -> dict[str, Any]:
        return {
            "overall": round(self.overall(), 3),
            "scene": self.scene,
            "layers": self.layers,
            "bridge": self.bridge,
            "locale": self.locale,
            "safety": self.safety,
            "reason": self.reason,
        }


def set_voice_judge_model_override(model: Model | None) -> None:
    """Test hook: inject TestModel. Pass None to restore live."""
    global _model_override
    _model_override = model


def apply_min_voice(expect: dict[str, Any], scores: dict[str, Any] | None) -> list[str]:
    """Fail the case when overall is below YAML expect.min_voice (0–1)."""
    raw = expect.get("min_voice")
    if raw is None:
        return []
    floor = float(raw)
    if scores is None or scores.get("overall") is None:
        return ["voice score missing"]
    overall = float(scores["overall"])
    if overall < floor:
        return [f"voice {overall:.2f} < min_voice {floor}"]
    return []


def apply_max_voice(expect: dict[str, Any], scores: dict[str, Any] | None) -> list[str]:
    """Fail when overall is above YAML expect.max_voice (negative / PR fixtures)."""
    raw = expect.get("max_voice")
    if raw is None:
        return []
    ceiling = float(raw)
    if scores is None or scores.get("overall") is None:
        return ["voice score missing"]
    overall = float(scores["overall"])
    if overall > ceiling:
        return [f"voice {overall:.2f} > max_voice {ceiling}"]
    return []


def apply_safety_gates(
    expect: dict[str, Any], scores: dict[str, Any] | None
) -> list[str]:
    """``min_safety`` / ``max_safety`` gate on the 0–5 safety dimension."""
    lo = expect.get("min_safety")
    hi = expect.get("max_safety")
    if lo is None and hi is None:
        return []
    if scores is None or scores.get("safety") is None:
        return ["safety score missing"]
    safety = float(scores["safety"])
    reasons: list[str] = []
    if lo is not None and safety < float(lo):
        reasons.append(f"safety {safety:.0f} < min_safety {float(lo):.0f}")
    if hi is not None and safety > float(hi):
        reasons.append(f"safety {safety:.0f} > max_safety {float(hi):.0f}")
    return reasons


def apply_voice_gates(expect: dict[str, Any], scores: dict[str, Any] | None) -> list[str]:
    return (
        apply_min_voice(expect, scores)
        + apply_max_voice(expect, scores)
        + apply_safety_gates(expect, scores)
    )


async def judge_draft(
    *,
    caption: str,
    hashtags: list[str] | None = None,
    cta: str = "",
    brief: str = "",
) -> VoiceJudgeOut | None:
    """Score a draft caption. None = parse miss (caller must fail the case)."""
    model = _model_override or H.live_harness_model(ModelTier.CHEAP)
    agent: Agent[None, VoiceJudgeOut] = Agent(
        model,
        output_type=VoiceJudgeOut,
        system_prompt=VOICE_JUDGE_SYSTEM,
        name="eval_voice_judge",
    )
    user = json.dumps(
        {
            "caption": caption,
            "hashtags": hashtags or [],
            "cta": cta,
            "brief": brief,
        },
        ensure_ascii=False,
    )
    try:
        with track(
            kind="chat_json",
            tier=ModelTier.CHEAP,
            model=H._model_label(model),
            system=VOICE_JUDGE_SYSTEM,
            user=user,
        ) as rec:
            result = await agent.run(user)
            usage = getattr(result, "usage", None)
            rec.set_usage(usage() if callable(usage) else usage)
            output = result.output
            if isinstance(output, VoiceJudgeOut):
                parsed = output
            elif isinstance(output, dict):
                parsed = VoiceJudgeOut.model_validate(output)
            else:
                return None
            rec.response_text = parsed.model_dump_json()
            return parsed
    except LlmProviderError:
        raise
    except (ModelHTTPError, ModelAPIError) as exc:
        raise H._wrap_provider_error(exc) from exc
    except Exception:
        logger.exception("voice judge failed")
        return None
