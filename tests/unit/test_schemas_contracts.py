import uuid

import pytest
from pydantic import ValidationError

from schemas.contracts import (
    CitedSignal,
    DraftCopy,
    PreviewUpdatedData,
    SessionEventType,
    SignalsUpdatedData,
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
    assert again.source_signal_ids == []
    assert again.sources == []


def test_preview_updated_includes_cited_signals() -> None:
    payload = PreviewUpdatedData(
        revision=1,
        approval_token="token-abc-12",
        draft_copy=DraftCopy(caption="x"),
        source_signal_ids=["sig_a"],
        sources=[
            CitedSignal(
                signal_id="sig_a",
                source="google_trends",
                title="奶茶",
                url="https://example.com/milk-tea",
                excerpt="HK trend",
            )
        ],
    )
    data = payload.model_dump(by_alias=True)
    assert data["source_signal_ids"] == ["sig_a"]
    assert data["sources"][0]["title"] == "奶茶"


def test_signals_updated_includes_cards() -> None:
    body = SignalsUpdatedData(
        source_signal_ids=["sig_a"],
        signals=[CitedSignal(signal_id="sig_a", source="rss", title="News")],
    )
    assert body.signals[0].title == "News"


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


def test_contracts_fresh_detects_drift(tmp_path, monkeypatch) -> None:
    import scripts.check_contracts_fresh as ccf

    (tmp_path / "docs" / "contracts").mkdir(parents=True)
    committed = tmp_path / "docs" / "contracts" / "draft-copy.schema.json"
    committed.write_text("{}")

    gen_dir = tmp_path / "gen"
    committed_dir = tmp_path / "committed"
    (committed_dir / "docs" / "contracts").mkdir(parents=True)
    committed = committed_dir / "docs" / "contracts" / "draft-copy.schema.json"
    committed.write_text("{}")

    class _FakeTmp:
        def __enter__(self):
            (gen_dir / "docs" / "contracts").mkdir(parents=True, exist_ok=True)
            return str(gen_dir)

        def __exit__(self, *exc) -> None:
            return None

    def fake_run(*args, **kwargs) -> None:
        generated = gen_dir / "docs" / "contracts" / "draft-copy.schema.json"
        generated.write_text('{"title": "generated"}')

    monkeypatch.setattr(ccf.subprocess, "run", fake_run)
    monkeypatch.setattr(ccf.tempfile, "TemporaryDirectory", _FakeTmp)
    monkeypatch.setattr(ccf, "ROOT", committed_dir)

    problems = ccf.regen_and_diff()
    assert problems
    assert "contracts/draft-copy.schema.json" in problems
