"""Unit tests for product catalog retrieve + org-wins cover + hybrid merge."""

from types import SimpleNamespace
from uuid import UUID

import pytest

from internal.memory.embeddings import cosine_similarity
from internal.memory.product_retrieve import (
    ProductHit,
    _member_scope_filter,
    dedupe_org_wins,
    hit_to_payload,
    merge_lexical_and_vector,
    pick_primary,
)


def _row(**kwargs):
    defaults = {
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "sku": "SKU-1",
        "name": "Oat Latte",
        "search_document": "Oat Latte | SKU-1 | 48",
        "owner_scope": "org",
        "profile": {},
        "embedding": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_dedupe_org_wins_on_sku_clash() -> None:
    org = ProductHit(product=_row(owner_scope="org", name="Org oat"), score=0.7, match_kind="fuzzy")
    user = ProductHit(
        product=_row(
            owner_scope="user",
            name="User oat",
            id=UUID("00000000-0000-0000-0000-000000000002"),
        ),
        score=0.99,
        match_kind="exact_sku",
    )
    hits = dedupe_org_wins([user, org])
    assert len(hits) == 1
    assert hits[0].product.owner_scope == "org"


def test_pick_primary_requires_margin() -> None:
    a = ProductHit(product=_row(sku="A"), score=0.8, match_kind="fuzzy")
    b = ProductHit(product=_row(sku="B", name="Other"), score=0.75, match_kind="fuzzy")
    primary, clarify = pick_primary([a, b])
    assert primary is None
    assert clarify is True

    clear = ProductHit(product=_row(sku="C"), score=0.95, match_kind="exact_sku")
    weak = ProductHit(product=_row(sku="D", name="D"), score=0.6, match_kind="fuzzy")
    primary, clarify = pick_primary([clear, weak])
    assert primary is clear
    assert clarify is False


def test_hit_to_payload_shape() -> None:
    hit = ProductHit(product=_row(), score=1.0, match_kind="exact_sku")
    payload = hit_to_payload(hit)
    assert payload["sku"] == "SKU-1"
    assert payload["source"] == "org_catalog"
    assert "48" in payload["search_document"]


def test_merge_prefers_exact_over_vector() -> None:
    pid = UUID("00000000-0000-0000-0000-000000000010")
    row = _row(id=pid)
    lexical = [ProductHit(product=row, score=1.0, match_kind="exact_sku")]
    vector = [ProductHit(product=row, score=0.7, match_kind="vector")]
    merged = merge_lexical_and_vector(lexical, vector)
    assert len(merged) == 1
    assert merged[0].match_kind == "exact_sku"
    assert merged[0].score >= 0.95


def test_merge_surfaces_vector_only_hit() -> None:
    lex_row = _row(id=UUID("00000000-0000-0000-0000-000000000011"), sku="A", name="A")
    vec_row = _row(
        id=UUID("00000000-0000-0000-0000-000000000012"),
        sku="B",
        name="Seasonal oat milk latte",
    )
    lexical = [ProductHit(product=lex_row, score=0.6, match_kind="fuzzy")]
    vector = [ProductHit(product=vec_row, score=0.88, match_kind="vector")]
    merged = merge_lexical_and_vector(lexical, vector)
    assert {h.product.sku for h in merged} == {"A", "B"}
    assert merged[0].product.sku == "B"


def test_cosine_similarity_identical() -> None:
    v = [0.0, 1.0, 0.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_member_scope_sql_binds_company_id() -> None:
    """COLLECT §6 — company_id is always in the SQL predicate (no global top-K)."""
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from internal.memory.models import Product

    cid = UUID("11111111-1111-1111-1111-111111111111")
    uid = UUID("22222222-2222-2222-2222-222222222222")
    stmt = select(Product).where(*_member_scope_filter(cid, uid))
    sql = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "11111111-1111-1111-1111-111111111111" in sql
    assert "company_id" in sql
