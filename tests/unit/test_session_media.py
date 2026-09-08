"""Pure helpers for ADR 0008 media."""

import uuid

from internal.session.media import image_format_from_plan, media_item_payload


def test_image_format_from_plan() -> None:
    assert image_format_from_plan(None) == "single"
    assert image_format_from_plan({"format": "comic_4panel"}) == "comic_4panel"
    assert image_format_from_plan({"format": "nope"}) == "single"


def test_media_item_payload() -> None:
    iid = uuid.UUID("00000000-0000-0000-0000-000000000099")
    item = media_item_payload(
        image_id=iid,
        url="https://cdn.example/x.png",
        plan={"prompt": "x"},
        format="single",
    )
    assert item["id"] == str(iid)
    assert item["url"] == "https://cdn.example/x.png"
    assert item["plan"]["prompt"] == "x"

    keyed = media_item_payload(
        image_id=iid,
        url="sessions/s1/r1-abcd1234.png",
        plan={},
        format="single",
    )
    assert keyed["url"] is not None
    assert keyed["url"].endswith("/api/media/sessions/s1/r1-abcd1234.png")
