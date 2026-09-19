"""Tests for image format helpers."""

from internal.session.image_format import (
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
