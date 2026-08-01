from internal.session.service import normalize_draft_copy, preview_updated_payload


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
