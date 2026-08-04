"""Pure helpers for ADR 0008 media."""

from internal.session.media import image_format_from_plan, media_item_payload
import uuid


def test_image_format_from_plan() -> None:
    assert image_format_from_plan(None) == "single"
    assert image_format_from_plan({"format": "comic_4panel"}) == "comic_4panel"
    assert image_format_from_plan({"format": "nope"}) == "single"


def test_media_item_payload() -> None:
    iid = uuid.UUID("00000000-0000-0000-0000-000000000099")
    item = media_item_payload(
        image_id=iid, url="u", plan={"prompt": "x"}, format="single"
    )
    assert item["id"] == str(iid)
    assert item["plan"]["prompt"] == "x"
