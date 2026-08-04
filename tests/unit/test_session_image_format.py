"""Tests for image format helpers."""

from internal.session.image_format import (
    compose_generation_prompt,
    image_format_from_text,
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
