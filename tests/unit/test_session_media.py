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
        image_id=iid, url="u", plan={"prompt": "x"}, format="single"
    )
    assert item["id"] == str(iid)
    assert item["plan"]["prompt"] == "x"


def test_media_item_payload_resolves_store_key(monkeypatch) -> None:
    from internal.media import storage as S

    monkeypatch.setattr(S.settings, "deployment_mode", "onprem")
    monkeypatch.setattr(S.settings, "s3_endpoint_url", None)
    monkeypatch.setattr(S.settings, "s3_bucket", None)
    monkeypatch.setattr(S.settings, "s3_access_key", None)
    monkeypatch.setattr(S.settings, "s3_secret_key", None)
    monkeypatch.setattr(S.settings, "web_base_url", "https://example.test")
    iid = uuid.UUID("00000000-0000-0000-0000-000000000099")
    item = media_item_payload(
        image_id=iid,
        url="sessions/abc/r1-deadbeef.png",
        plan={},
        format="single",
    )
    assert item["url"] == "https://example.test/api/media/sessions/abc/r1-deadbeef.png"


def test_preview_updated_payload_resolves_store_key(monkeypatch) -> None:
    """preview.updated emit path: store key → browser-fetchable URL (ADR 0024 §3)."""
    from internal.media import storage as S
    from internal.media.config import reset_snapshot_cache
    from internal.session.service import preview_updated_payload

    monkeypatch.setattr(S.settings, "deployment_mode", "onprem")
    monkeypatch.setattr(S.settings, "s3_endpoint_url", None)
    monkeypatch.setattr(S.settings, "s3_bucket", None)
    monkeypatch.setattr(S.settings, "s3_access_key", None)
    monkeypatch.setattr(S.settings, "s3_secret_key", None)
    monkeypatch.setattr(S.settings, "web_base_url", "https://example.test")
    reset_snapshot_cache()

    payload = preview_updated_payload(
        revision=2,
        approval_token="tok",
        image_url="sessions/abc/r2-deadbeef.png",
        copy={"caption": "hi", "hashtags": [], "cta": ""},
    )
    assert (
        payload["image_url"]
        == "https://example.test/api/media/sessions/abc/r2-deadbeef.png"
    )
