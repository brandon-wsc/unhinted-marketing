"""Tests for image format helpers."""

from internal.session.image_format import (
    SINGLE_COMPOSITION,
    SINGLE_STYLE,
    adapt_plan_to_format,
    compose_generation_prompt,
    image_format_from_text,
    lock_brief_to_format,
    normalize_image_format,
)


def test_normalize_image_format() -> None:
    assert normalize_image_format(None) == "single"
    assert normalize_image_format("comic_4panel") == "comic_4panel"
    assert normalize_image_format("nope") == "single"


def test_image_format_from_text() -> None:
    assert image_format_from_text("幫我整4格漫畫") == "comic_4panel"
    assert image_format_from_text("改做單圖") == "single"
    assert image_format_from_text("改下 caption") is None


def test_compose_generation_prompt_comic() -> None:
    prompt = compose_generation_prompt(
        {
            "format": "comic_4panel",
            "prompt": "HK cafe mood",
            "panels": [
                {"index": 1, "beat": "tired office"},
                {"index": 2, "beat": "queue chaos"},
                {"index": 3, "beat": "product appears"},
                {"index": 4, "beat": "soft smile"},
            ],
            "style": "line comic",
            "avoid": ["logos"],
        }
    )
    assert "4-panel" in prompt
    assert "Panel 1: tired office" in prompt
    assert "HK cafe mood" in prompt
    assert "Avoid: logos" in prompt


def test_lock_brief_to_format_replaces_contradictory_photo_lines() -> None:
    """UAT S3: sticky comic must not keep a 生活照 / 唔需要漫畫分格 can_do."""
    locked = lock_brief_to_format(
        {
            "can_do": [
                "格式：1 張暖調生活照；唔需要漫畫分格",
                "語氣定調：溫柔、慢半拍",
            ],
            "cannot_do": ["未 Confirm 唔發佈", "唔可以將 4 格畫成 6–8 格"],
            "angles": ["凍咗嘅茶"],
            "summary": "溫柔少抽水",
        },
        "comic_4panel",
    )
    assert locked["angles"] == ["凍咗嘅茶"]
    assert any("4 格漫畫" in line for line in locked["can_do"])
    assert "語氣定調：溫柔、慢半拍" in locked["can_do"]
    assert not any("生活照" in line or "唔需要漫畫" in line for line in locked["can_do"])
    assert any("單圖" in line or "生活照" in line for line in locked["cannot_do"])


def test_lock_brief_to_format_single_drops_comic_vehicle() -> None:
    locked = lock_brief_to_format(
        {
            "can_do": ["格式定為 4 格漫畫（IG carousel）", "短 caption"],
            "cannot_do": ["未 Confirm 唔發佈"],
        },
        "single",
    )
    assert any("單圖" in line for line in locked["can_do"])
    assert "短 caption" in locked["can_do"]
    assert not any("4 格漫畫" in line for line in locked["can_do"])


_COMIC_PLAN = {
    "format": "comic_4panel",
    "prompt": (
        "4-panel comic strip for Acme, Hong Kong everyday scenes "
        "inspired by: 凍咗嘅茶, clear gutters, no logos"
    ),
    "composition": "2x2 comic grid, equal panels, reading L→R then top→bottom",
    "style": "clean line comic, contemporary HK urban",
    "panels": [
        {"index": 1, "beat": "tired office"},
        {"index": 2, "beat": "queue chaos"},
        {"index": 3, "beat": "peak pain"},
        {"index": 4, "beat": "soft smile"},
    ],
}


def test_adapt_plan_comic_to_single_rewrites_vehicle() -> None:
    """UAT S2: stamped format=single must not keep 4-panel prompt / panels."""
    adapted = adapt_plan_to_format(
        {**_COMIC_PLAN, "format": "single"},
        "single",
        previous_format="comic_4panel",
    )
    assert adapted["format"] == "single"
    assert adapted["panels"] == []
    assert adapted["composition"] == SINGLE_COMPOSITION
    assert adapted["style"] == SINGLE_STYLE
    assert "4-panel" not in adapted["prompt"].lower()
    assert "凍咗嘅茶" in adapted["prompt"]
    prompt = compose_generation_prompt(adapted)
    assert "4-panel" not in prompt.lower()
    assert "Panel 1:" not in prompt


def test_adapt_plan_single_to_comic_fills_panels() -> None:
    adapted = adapt_plan_to_format(
        {
            "format": "single",
            "prompt": "HK cafe mood",
            "composition": SINGLE_COMPOSITION,
            "style": SINGLE_STYLE,
            "panels": [],
        },
        "comic_4panel",
        previous_format="single",
    )
    assert adapted["format"] == "comic_4panel"
    assert len(adapted["panels"]) == 4
    assert "2x2 comic" in adapted["composition"]
    prompt = compose_generation_prompt(adapted)
    assert "4-panel" in prompt
    assert "HK cafe mood" in prompt


def test_adapt_plan_comic_to_single_rewrites_layout_composition() -> None:
    """UAT: '2x2 grid / four equal panels' composition has no comic keywords —
    COMIC_VEHICLE alone misses it and regen would still paint a grid."""
    adapted = adapt_plan_to_format(
        {
            **_COMIC_PLAN,
            "format": "single",
            "composition": (
                "One image divided into a 2x2 grid of four equal panels "
                "with clear gutters. Panel order: top-left 1, top-right 2."
            ),
        },
        "single",
        previous_format="comic_4panel",
    )
    assert adapted["composition"] == SINGLE_COMPOSITION


def test_adapt_plan_keeps_custom_single_prompt() -> None:
    adapted = adapt_plan_to_format(
        {
            "format": "single",
            "prompt": "Warm street photo of a milk tea cup",
            "composition": "tight crop on the cup",
            "style": "film still",
            "panels": [
                {"index": 1, "beat": "leftover"},
            ],
        },
        "single",
        previous_format="comic_4panel",
    )
    assert adapted["panels"] == []
    assert adapted["prompt"] == "Warm street photo of a milk tea cup"
    assert adapted["composition"] == "tight crop on the cup"
    assert adapted["style"] == "film still"
