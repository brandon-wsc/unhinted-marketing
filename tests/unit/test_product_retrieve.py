"""Unit tests for product catalog retrieve + org-wins cover."""

from types import SimpleNamespace

from internal.memory.product_retrieve import (
    ProductHit,
    dedupe_org_wins,
    hit_to_payload,
    pick_primary,
)


def _row(**kwargs):
    defaults = {
        "id": "00000000-0000-0000-0000-000000000001",
        "sku": "SKU-1",
        "name": "Oat Latte",
        "search_document": "Oat Latte | SKU-1 | 48",
        "owner_scope": "org",
        "profile": {},
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_dedupe_org_wins_on_sku_clash() -> None:
    org = ProductHit(product=_row(owner_scope="org", name="Org oat"), score=0.7, match_kind="fuzzy")
    user = ProductHit(
        product=_row(
            owner_scope="user",
            name="User oat",
            id="00000000-0000-0000-0000-000000000002",
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
