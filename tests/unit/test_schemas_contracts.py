import uuid

import pytest
from pydantic import ValidationError

from schemas.contracts import (
    DraftCopy,
    PreviewUpdatedData,
    SessionEventType,
    TypedSessionEvent,
)
from schemas.tools import (
    PublishSocialPostRequest,
    QueryMarketTrendsRequest,
    QueryMarketTrendsResponse,
)


def test_draft_copy_defaults() -> None:
    copy = DraftCopy()
    assert copy.caption == ""
    assert copy.hashtags == []
    assert copy.cta == ""


def test_preview_updated_roundtrip() -> None:
    payload = PreviewUpdatedData(
        revision=3,
        approval_token="token-abc-12",
        image_url=None,
        draft_copy=DraftCopy(caption="你好", hashtags=["#HK"], cta="了解更多"),
        platform="instagram",
    )
    data = payload.model_dump(by_alias=True)
    assert data["copy"]["caption"] == "你好"
    again = PreviewUpdatedData.model_validate(data)
    assert again.revision == 3
    assert again.draft_copy.caption == "你好"


def test_session_event_type_catalog_includes_preview() -> None:
    assert SessionEventType.PREVIEW_UPDATED == "preview.updated"
    assert SessionEventType.MESSAGE_DELTA == "message.delta"
    ev = TypedSessionEvent(type="preview.updated", data={"revision": 1})
    assert ev.known_type() is SessionEventType.PREVIEW_UPDATED
    assert TypedSessionEvent(type="future.unknown").known_type() is None


def test_query_market_trends_request_bounds() -> None:
    ok = QueryMarketTrendsRequest(region="HK", limit=10)
    assert ok.limit == 10
    with pytest.raises(ValidationError):
        QueryMarketTrendsRequest(limit=0)


def test_query_market_trends_response() -> None:
    body = QueryMarketTrendsResponse(
        region="HK",
        signals=[
            {
                "signal_id": "sig_1",
                "source": "google_trends",
                "title": "奶茶",
                "metrics": {"rank": 1},
            }
        ],
        ranked_signal_ids=["sig_1"],
        notes="top",
    )
    assert body.signals[0].signal_id == "sig_1"


def test_publish_social_post_requires_token() -> None:
    with pytest.raises(ValidationError):
        PublishSocialPostRequest(
            session_id=uuid.uuid4(),
            approval_token="short",
            idempotency_key="idem-key-12",
            draft_copy=DraftCopy(caption="x"),
            revision=1,
        )


def test_publish_social_post_ok() -> None:
    body = PublishSocialPostRequest(
        session_id=uuid.uuid4(),
        approval_token="token-ok-12",
        idempotency_key="idem-key-12",
        draft_copy=DraftCopy(caption="hello", hashtags=["#a"], cta="go"),
        revision=2,
        platform="stub",
    )
    assert body.draft_copy.caption == "hello"
    assert body.model_dump(by_alias=True)["copy"]["caption"] == "hello"
    assert body.revision == 2


def test_export_contracts_respects_export_root(tmp_path, monkeypatch) -> None:
    import scripts.export_contracts as ec

    monkeypatch.setenv("EXPORT_ROOT", str(tmp_path))
    tmp_contracts = tmp_path / "docs" / "contracts"
    monkeypatch.setattr(ec, "CONTRACTS_DIR", tmp_contracts)
    monkeypatch.setattr(ec, "OPENAPI_PATH", tmp_path / "docs" / "openapi.json")

    ec.export_json_schemas()
    ec.export_openapi()

    assert (tmp_contracts / "draft-copy.schema.json").exists()
    assert (tmp_path / "docs" / "openapi.json").exists()


def test_ts_mirror_guard_catches_missing_keys(tmp_path, monkeypatch) -> None:
    import scripts.check_contracts_fresh as ccf

    mirror = tmp_path / "types.ts"
    mirror.write_text("export type PreviewDraft = { copy: DraftCopy };")
    monkeypatch.setattr(ccf, "TYPE_MIRROR", mirror)

    problems = ccf.check_ts_mirror()
    assert problems
    assert any("revision" in p for p in problems)
