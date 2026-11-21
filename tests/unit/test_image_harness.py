"""ADR 0062 image_harness — plan_image tool body, mocked LLM."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from internal.session import image_harness as IH
from tests.unit.lc_fakes import _ScriptedChat, out_call


@pytest.fixture(autouse=True)
def _clear_override() -> None:
    IH.set_plan_model_override(None)
    yield
    IH.set_plan_model_override(None)


def _scripted(*msgs: AIMessage | str) -> _ScriptedChat:
    return _ScriptedChat(
        messages=iter([AIMessage(content=m) if isinstance(m, str) else m for m in msgs])
    )


def _payload(**extra) -> dict:
    base = {
        "draft": {"caption": "cap", "hashtags": [], "cta": "c"},
        "brief": {"angles": ["a"]},
        "company": {"name": "美心"},
        "voice_pack": {"roast_level": 1, "locale": "zh-HK", "extra": "dropped"},
        "image_format": "single",
    }
    base.update(extra)
    return base


@pytest.mark.asyncio
async def test_run_plan_image_parsed_plan_normalized() -> None:
    """Parsed ImagePlanOut → merged avoids, normalized format, panels kept."""
    IH.set_plan_model_override(
        _scripted(
            out_call(
                "ImagePlanOut",
                {
                    "prompt": "comic prompt",
                    "format": "comic_4panel",
                    "avoid": ["logos"],
                    "panels": [{"index": 1, "beat": "hook"}],
                },
            )
        )
    )
    result = await IH.run_plan_image(_payload(image_format="comic_4panel"))
    plan = result.state_update["image_plan"]
    assert plan["format"] == "comic_4panel"
    assert plan["panels"] == [{"index": 1, "beat": "hook"}]
    assert "logos" in plan["avoid"]
    assert result.state_update["image_format"] == "comic_4panel"
    assert json.loads(result.reply) == {"planned": True, "format": "comic_4panel"}


@pytest.mark.asyncio
async def test_run_plan_image_non_comic_drops_panels() -> None:
    """A single-format plan never carries panels (vertex rule, preserved)."""
    IH.set_plan_model_override(
        _scripted(
            out_call(
                "ImagePlanOut",
                {
                    "prompt": "single prompt",
                    "format": "single",
                    "panels": [{"index": 1, "beat": "stray"}],
                },
            )
        )
    )
    result = await IH.run_plan_image(_payload())
    plan = result.state_update["image_plan"]
    assert plan["format"] == "single"
    assert plan["panels"] == []


@pytest.mark.asyncio
async def test_run_plan_image_fallback_single() -> None:
    """Parse miss → deterministic single-format fallback mentioning the caption."""
    IH.set_plan_model_override(_scripted("not structured"))
    result = await IH.run_plan_image(_payload(draft={"caption": "茶餐廳文化"}))
    plan = result.state_update["image_plan"]
    assert plan["format"] == "single"
    assert "美心" in plan["prompt"]
    assert "茶餐廳文化" in plan["prompt"]
    assert result.state_update["image_format"] == "single"


@pytest.mark.asyncio
async def test_run_plan_image_fallback_comic() -> None:
    """Parse miss + comic format → 4-panel fallback with default beats."""
    IH.set_plan_model_override(_scripted("not structured"))
    result = await IH.run_plan_image(_payload(image_format="comic_4panel"))
    plan = result.state_update["image_plan"]
    assert plan["format"] == "comic_4panel"
    assert len(plan["panels"]) == 4
    assert result.state_update["image_format"] == "comic_4panel"
