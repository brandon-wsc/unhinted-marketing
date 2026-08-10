"""Product catalog retrieve for session product_matcher (COLLECT Tier A/B)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory.models import Product

# Primary: top-1 score floor + margin vs #2 (COLLECT §5).
PRIMARY_MIN_SCORE = 0.55
PRIMARY_MARGIN = 0.12


@dataclass(frozen=True)
class ProductHit:
    product: Product
    score: float
    match_kind: str  # exact_sku | fuzzy


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip()).lower()


def _queries_clean(queries: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in queries:
        if not isinstance(raw, str):
            continue
        q = raw.strip()
        if len(q) < 1:
            continue
        key = _norm(q)
        if key in seen:
            continue
        seen.add(key)
        out.append(q[:200])
        if len(out) >= 5:
            break
    return out


def dedupe_org_wins(hits: list[ProductHit]) -> list[ProductHit]:
    """Same SKU → keep org row (cover rule)."""
    by_sku: dict[str, ProductHit] = {}
    for hit in hits:
        sku_key = hit.product.sku.strip().lower()
        prev = by_sku.get(sku_key)
        if prev is None:
            by_sku[sku_key] = hit
            continue
        if hit.product.owner_scope == "org" and prev.product.owner_scope != "org":
            by_sku[sku_key] = hit
            continue
        if prev.product.owner_scope == "org" and hit.product.owner_scope != "org":
            continue
        if hit.score > prev.score:
            by_sku[sku_key] = hit
    ranked = list(by_sku.values())
    ranked.sort(
        key=lambda h: (
            -h.score,
            0 if h.product.owner_scope == "org" else 1,
            h.product.name.lower(),
        )
    )
    return ranked


def pick_primary(hits: list[ProductHit]) -> tuple[ProductHit | None, bool]:
    """Return (primary, need_clarify)."""
    if not hits:
        return None, False
    top = hits[0]
    if top.score < PRIMARY_MIN_SCORE:
        return None, True
    if len(hits) >= 2 and (top.score - hits[1].score) < PRIMARY_MARGIN:
        return None, True
    return top, False


def hit_to_payload(hit: ProductHit) -> dict:
    doc = (hit.product.search_document or "").strip()
    return {
        "product_id": str(hit.product.id),
        "sku": hit.product.sku,
        "name": hit.product.name,
        "search_document": doc[:800],
        "match_score": round(hit.score, 4),
        "source": "org_catalog" if hit.product.owner_scope == "org" else "user_catalog",
        "match_kind": hit.match_kind,
    }


async def search_products_for_member(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    queries: list[str],
    limit: int = 5,
) -> list[ProductHit]:
    """Tenant-scoped org∪user search. Never call without company_id."""
    cleaned = _queries_clean(queries)
    if not cleaned:
        return []

    base = (
        select(Product)
        .where(
            Product.company_id == company_id,
            Product.status == "active",
            or_(
                Product.owner_scope == "org",
                (Product.owner_scope == "user") & (Product.user_id == user_id),
            ),
        )
    )
    rows = list((await db.scalars(base)).all())
    if not rows:
        return []

    hits: list[ProductHit] = []
    for row in rows:
        best = 0.0
        kind = "fuzzy"
        sku_l = row.sku.strip().lower()
        name_l = row.name.strip().lower()
        doc_l = (row.search_document or "").lower()
        for q in cleaned:
            qn = _norm(q)
            if not qn:
                continue
            if qn == sku_l or qn == name_l:
                best = max(best, 1.0)
                kind = "exact_sku"
                continue
            if sku_l and (qn in sku_l or sku_l in qn):
                best = max(best, 0.92)
                kind = "exact_sku" if best >= 0.92 else kind
                continue
            if name_l and qn in name_l:
                best = max(best, 0.8)
                continue
            if name_l and name_l in qn and len(name_l) >= 2:
                best = max(best, 0.72)
                continue
            if doc_l and qn in doc_l:
                # Longer query substring → slightly higher
                ratio = min(len(qn) / max(len(doc_l), 1), 1.0)
                best = max(best, 0.55 + 0.25 * ratio)
        if best > 0:
            hits.append(ProductHit(product=row, score=best, match_kind=kind))

    return dedupe_org_wins(hits)[: max(1, limit)]
