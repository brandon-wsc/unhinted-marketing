"""Unit tests for company settings schemas (voice + products)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from schemas.company import (
    CompanyVoiceUpdate,
    ExemplarPromoteRequest,
    ProductCreateRequest,
    ProductImportResponse,
    ProductItem,
    ProductListResponse,
)


def test_voice_update_strips_and_caps_exemplars() -> None:
    body = CompanyVoiceUpdate(
        roast_level=1,
        locale="  zh-HK  ",
        forbidden_phrases=[" a ", "a", "b", ""],
        tone_notes="  hello  ",
        exemplar_captions=["  one  ", "one", "a" * 200],
    )
    assert body.locale == "zh-HK"
    assert body.tone_notes == "hello"
    assert body.forbidden_phrases == ["a", "b"]
    assert body.exemplar_captions == ["one", "a" * 150]


def test_voice_update_forbidden_hits_cap() -> None:
    body = CompanyVoiceUpdate(
        roast_level=1,
        locale="zh-HK",
        forbidden_phrases=[f"p{i}" for i in range(15)],
        tone_notes="",
        exemplar_captions=[],
    )
    assert len(body.forbidden_phrases) == 15


def test_voice_update_exemplar_max_three() -> None:
    body = CompanyVoiceUpdate(
        roast_level=1,
        locale="zh-HK",
        forbidden_phrases=[],
        tone_notes="",
        exemplar_captions=["one", "two", "three"],
    )
    assert body.exemplar_captions == ["one", "two", "three"]


def test_voice_update_rejects_blank_locale() -> None:
    with pytest.raises(ValidationError):
        CompanyVoiceUpdate(
            roast_level=1,
            locale="   ",
            forbidden_phrases=[],
            tone_notes="",
            exemplar_captions=[],
        )


def test_exemplar_promote_strips_caption() -> None:
    body = ExemplarPromoteRequest(caption="  keep me  ")
    assert body.caption == "keep me"
    with pytest.raises(ValidationError):
        ExemplarPromoteRequest(caption="   ")


def test_product_create_strips_fields() -> None:
    body = ProductCreateRequest(name="  Oat  ", sku="  SKU-1  ", notes="  n  ")
    assert body.name == "Oat"
    assert body.sku == "SKU-1"
    assert body.notes == "n"
    with pytest.raises(ValidationError):
        ProductCreateRequest(name="  ", sku="x")


def test_product_list_and_import_shapes() -> None:
    pid = uuid.uuid4()
    cid = uuid.uuid4()
    item = ProductItem(
        id=pid,
        sku="SKU-1",
        name="Oat",
        status="active",
        owner_scope="org",
        covered_by_company=False,
        profile={"name": "Oat"},
        updated_at=datetime.now(UTC),
    )
    listed = ProductListResponse(company_id=cid, scope="org", items=[item], can_edit=True)
    assert listed.items[0].sku == "SKU-1"
    imp = ProductImportResponse(imported=1, updated=0, skipped=0, errors=[])
    assert imp.imported == 1
