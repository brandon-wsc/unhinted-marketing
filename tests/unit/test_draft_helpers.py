from types import SimpleNamespace

from internal.session.service import (
    cited_signals_from_rows,
    normalize_draft_copy,
    preview_updated_payload,
    unique_signal_ids,
)


def test_normalize_draft_copy_none() -> None:
    assert normalize_draft_copy(None) == {
        "caption": "",
        "hashtags": [],
        "cta": "",
    }


def test_normalize_draft_copy_coerces_fields() -> None:
    out = normalize_draft_copy(
        {
            "caption": 123,
            "hashtags": ["a", " ", "b", 9],
            "cta": None,
        }
    )
    assert out["caption"] == "123"
    assert out["hashtags"] == ["a", "b", "9"]
    assert out["cta"] == ""


def test_normalize_draft_copy_bad_hashtags_type() -> None:
    out = normalize_draft_copy({"caption": "hi", "hashtags": "not-a-list", "cta": "go"})
    assert out["hashtags"] == []
    assert out["caption"] == "hi"
    assert out["cta"] == "go"


def test_preview_updated_payload_defaults_platform() -> None:
    payload = preview_updated_payload(
        revision=2,
        approval_token="tok",
        image_url=None,
        copy={"caption": "c", "hashtags": ["x"], "cta": ""},
    )
    assert payload["revision"] == 2
    assert payload["approval_token"] == "tok"
    assert payload["platform"] == "instagram"
    assert payload["copy"]["hashtags"] == ["x"]
    assert payload["media"] == []


def test_preview_updated_payload_with_media() -> None:
    payload = preview_updated_payload(
        revision=1,
        approval_token="tok",
        image_url=None,
        copy={"caption": "c"},
        media=[
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "url": "https://cdn/x.png",
                "plan": {"prompt": "p"},
                "format": "comic_4panel",
                "role": "primary",
                "seq": 0,
                "status": "ready",
            }
        ],
    )
    assert payload["image_url"] == "https://cdn/x.png"
    assert payload["media"][0]["format"] == "comic_4panel"


def test_preview_updated_payload_custom_platform() -> None:
    payload = preview_updated_payload(
        revision=1,
        approval_token="tok",
        image_url="placeholder://x",
        copy=None,
        platform="threads",
    )
    assert payload["platform"] == "threads"
    assert payload["image_url"] == "placeholder://x"
    assert payload["copy"] == {"caption": "", "hashtags": [], "cta": ""}
    assert payload["source_signal_ids"] == []
    assert payload["sources"] == []


def test_unique_signal_ids_dedupes_and_skips_blank() -> None:
    assert unique_signal_ids(["a", "a", "", None, "b"]) == ["a", "b"]


def test_cited_signals_from_rows_preserves_citation_order() -> None:
    rows = [
        SimpleNamespace(
            signal_id="sig_b",
            source="google_trends",
            title="Second",
            url="https://example.com/b",
            excerpt="b",
        ),
        SimpleNamespace(
            signal_id="sig_a",
            source="rss",
            title="First",
            url="https://example.com/a",
            excerpt="a",
        ),
    ]
    cited = cited_signals_from_rows(rows, ["sig_a", "missing", "sig_b"])
    assert [c.signal_id for c in cited] == ["sig_a", "sig_b"]
    assert cited[0].title == "First"
    assert cited[0].url == "https://example.com/a"


def test_preview_updated_payload_includes_cited_sources() -> None:
    payload = preview_updated_payload(
        revision=2,
        approval_token="tok",
        image_url=None,
        copy={"caption": "c"},
        source_signal_ids=["sig_a"],
        sources=[
            {
                "signal_id": "sig_a",
                "source": "google_trends",
                "title": "HK typhoon",
                "url": "https://example.com/typhoon",
                "excerpt": "weather",
            }
        ],
    )
    assert payload["source_signal_ids"] == ["sig_a"]
    assert payload["sources"][0]["title"] == "HK typhoon"
    assert payload["sources"][0]["url"] == "https://example.com/typhoon"
