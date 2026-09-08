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


def test_preview_updated_payload_derives_object_key() -> None:
    payload = preview_updated_payload(
        revision=1,
        approval_token="tok",
        image_url="sessions/s1/r1-abcd1234.png",
        copy=None,
    )
    assert payload["image_url"] is not None
    assert payload["image_url"].endswith("/api/media/sessions/s1/r1-abcd1234.png")
