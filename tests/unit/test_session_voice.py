"""Tests for HK social craft / roast_level helpers."""

from internal.session.voice import (
    DEFAULT_ROAST_LEVEL,
    normalize_roast_level,
    roast_level_from_profile,
    voice_context,
)


def test_normalize_roast_level_clamps_and_defaults() -> None:
    assert normalize_roast_level(None) == DEFAULT_ROAST_LEVEL
    assert normalize_roast_level("nope") == DEFAULT_ROAST_LEVEL
    assert normalize_roast_level(-1) == 0
    assert normalize_roast_level(99) == 3
    assert normalize_roast_level("2") == 2


def test_voice_context_includes_label_and_optional_keys() -> None:
    empty = voice_context(None)
    assert empty["roast_level"] == 1
    assert empty["craft"] == "hk_social_editor"
    assert "輕鬆" in empty["roast_level_label"]

    rich = voice_context(
        {
            "roast_level": 0,
            "locale": "zh-HK",
            "tone_notes": "no slang",
            "forbidden_phrases": ["賦能"],
            "ignored": True,
        }
    )
    assert rich["roast_level"] == 0
    assert rich["locale"] == "zh-HK"
    assert rich["tone_notes"] == "no slang"
    assert rich["forbidden_phrases"] == ["賦能"]
    assert "ignored" not in rich


def test_roast_level_from_profile() -> None:
    assert roast_level_from_profile({}) == 1
    assert roast_level_from_profile({"roast_level": 3}) == 3
