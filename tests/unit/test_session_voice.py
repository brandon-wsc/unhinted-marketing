"""Tests for HK social craft / roast_level / voice_pack helpers."""

from types import SimpleNamespace

from internal.session.voice import (
    DEFAULT_ROAST_LEVEL,
    audience_catalog_entry,
    audience_catalog_from_entities,
    normalize_roast_level,
    pick_active_persona,
    roast_level_from_profile,
    voice_context,
    voice_pack,
)


def test_normalize_roast_level_clamps_and_defaults() -> None:
    assert normalize_roast_level(None) == DEFAULT_ROAST_LEVEL
    assert normalize_roast_level("nope") == DEFAULT_ROAST_LEVEL
    assert normalize_roast_level(-1) == 0
    assert normalize_roast_level(99) == 3
    assert normalize_roast_level("2") == 2


def test_voice_pack_includes_locale_and_caps_forbidden() -> None:
    empty = voice_pack(None)
    assert empty["roast_level"] == 1
    assert empty["craft"] == "hk_social_editor"
    assert empty["locale"] == "zh-HK"
    assert "輕鬆" in empty["roast_level_label"]

    rich = voice_pack(
        {
            "roast_level": 0,
            "locale": "zh-HK",
            "tone_notes": "no slang",
            "forbidden_phrases": [f"w{i}" for i in range(20)],
            "exemplar_captions": ["a" * 200, "short", 12, ""],
            "ignored": True,
        }
    )
    assert rich["roast_level"] == 0
    assert rich["locale"] == "zh-HK"
    assert rich["tone_notes"] == "no slang"
    assert len(rich["forbidden_phrases"]) == 15
    assert rich["exemplar_captions"] == ["a" * 150, "short"]
    assert "ignored" not in rich


def test_voice_context_alias() -> None:
    assert voice_context({"roast_level": 2})["roast_level"] == 2


def test_roast_level_from_profile() -> None:
    assert roast_level_from_profile({}) == 1
    assert roast_level_from_profile({"roast_level": 3}) == 3


def test_prepend_exemplar_caption_caps_and_dedupes() -> None:
    from internal.session.voice import prepend_exemplar_caption

    first = prepend_exemplar_caption([], "  hello world  ")
    assert first == ["hello world"]
    again = prepend_exemplar_caption(first, "hello world")
    assert again == ["hello world"]
    third = prepend_exemplar_caption(["a", "b", "c"], "new one")
    assert third == ["new one", "a", "b"]


def test_audience_catalog_from_entities() -> None:
    personas = [
        SimpleNamespace(
            slug="hk-young-professional",
            name="HK Young Professional",
            profile={
                "label": "YP",
                "content_preferences": ["Short-form"],
                "description": "long text ignored when prefs exist",
            },
        )
    ]
    catalog = audience_catalog_from_entities(personas)
    assert catalog == [
        {"slug": "hk-young-professional", "label": "YP", "hook": "Short-form"}
    ]
    assert pick_active_persona(catalog, "missing")["slug"] == "hk-young-professional"
    assert pick_active_persona(catalog, "hk-young-professional")["label"] == "YP"
    assert audience_catalog_entry(slug="x", profile={"description": "hook text"})["hook"] == (
        "hook text"
    )
