"""Product catalog retrieve for session product_matcher (COLLECT Tier A/B/C)."""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from internal.memory.embeddings import embed_query
from internal.memory.models import Product

# Primary: top-1 score floor + margin vs #2 (COLLECT §5).
PRIMARY_MIN_SCORE = 0.55
PRIMARY_MARGIN = 0.12
# Tier C cosine floor (normalized MiniLM); below → ignore vector hit.
VECTOR_MIN_SCORE = 0.42
RRF_K = 60
# Candidate pool pulled from pgvector for RRF fusion (final list is limit-sized).
VECTOR_TOP_K = 20


@dataclass(frozen=True)
class ProductHit:
    product: Product
    score: float
    match_kind: str  # exact_sku | fuzzy | vector


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


_KIND_RANK = {"exact_sku": 0, "fuzzy": 1, "vector": 2}


def merge_lexical_and_vector(
    lexical: list[ProductHit],
    vector: list[ProductHit],
) -> list[ProductHit]:
    """RRF rank fusion, then score = max(lex, vec, scaled RRF) for pick_primary."""
    if not vector:
        return lexical
    if not lexical:
        return vector

    rrf: dict[uuid.UUID, float] = {}
    best: dict[uuid.UUID, ProductHit] = {}

    for lst in (lexical, vector):
        for rank, hit in enumerate(lst, start=1):
            pid = hit.product.id
            rrf[pid] = rrf.get(pid, 0.0) + 1.0 / (RRF_K + rank)
            prev = best.get(pid)
            if prev is None:
                best[pid] = hit
                continue
            # Prefer stronger absolute score; break ties by match kind.
            if hit.score > prev.score or (
                hit.score == prev.score
                and _KIND_RANK.get(hit.match_kind, 9) < _KIND_RANK.get(prev.match_kind, 9)
            ):
                best[pid] = hit

    # Scale dual rank-1 ≈ 2/(60+1) * 30 ≈ 0.98
    scale = float(RRF_K) / 2.0
    fused: list[ProductHit] = []
    for pid, hit in best.items():
        scaled = min(1.0, rrf.get(pid, 0.0) * scale)
        score = max(hit.score, scaled)
        fused.append(ProductHit(product=hit.product, score=score, match_kind=hit.match_kind))

    fused.sort(
        key=lambda h: (
            -h.score,
            _KIND_RANK.get(h.match_kind, 9),
            0 if h.product.owner_scope == "org" else 1,
            h.product.name.lower(),
        )
    )
    return fused


def _lexical_hits(rows: list[Product], cleaned: list[str]) -> list[ProductHit]:
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
            if qn in (sku_l, name_l):
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
                ratio = min(len(qn) / max(len(doc_l), 1), 1.0)
                best = max(best, 0.55 + 0.25 * ratio)
        if best > 0:
            hits.append(ProductHit(product=row, score=best, match_kind=kind))
    hits.sort(key=lambda h: (-h.score, 0 if h.product.owner_scope == "org" else 1))
    return hits


def _lexical_where(cleaned: list[str]):
    """SQL superset of the ``_lexical_hits`` positive conditions.

    Every clause that can raise a row's score above 0 is a substring test in
    either direction (query in column, or column in query) — expressed here as
    ``strpos`` on lowercased text so Postgres narrows the candidate set.
    Scoring itself still happens in Python, so hit kinds/scores are unchanged.
    """
    conds = []
    for q in cleaned:
        qn = _norm(q)
        if not qn:
            continue
        conds.append(
            or_(
                func.strpos(func.lower(Product.sku), qn) > 0,
                func.strpos(qn, func.lower(Product.sku)) > 0,
                func.strpos(func.lower(Product.name), qn) > 0,
                func.strpos(qn, func.lower(Product.name)) > 0,
                func.strpos(func.lower(Product.search_document), qn) > 0,
            )
        )
    return or_(*conds) if conds else None


def _member_scope_filter(company_id: uuid.UUID, user_id: uuid.UUID):
    return (
        Product.company_id == company_id,
        Product.status == "active",
        or_(
            Product.owner_scope == "org",
            (Product.owner_scope == "user") & (Product.user_id == user_id),
        ),
    )


async def search_products_for_member(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    queries: list[str],
    limit: int = 5,
) -> list[ProductHit]:
    """Tenant-scoped org∪user hybrid search. Never call without company_id."""
    cleaned = _queries_clean(queries)
    if not cleaned:
        return []

    # Always filter company_id in SQL — never global vector top-K then filter (COLLECT §6).
    scope = _member_scope_filter(company_id, user_id)

    lexical: list[ProductHit] = []
    lexical_where = _lexical_where(cleaned)
    if lexical_where is not None:
        stmt = select(Product).options(defer(Product.embedding)).where(*scope).where(lexical_where)
        lexical = _lexical_hits(list((await db.scalars(stmt)).all()), cleaned)

    # Tier C runs in Postgres via pgvector <=> — no row scan in Python.
    query_vec = await asyncio.to_thread(embed_query, " ".join(cleaned))
    vector: list[ProductHit] = []
    if query_vec is not None:
        dist = Product.embedding.cosine_distance(query_vec).label("cosine_dist")
        stmt = (
            select(Product, dist)
            .options(defer(Product.embedding))
            .where(*scope)
            .where(Product.embedding.isnot(None))
            .where(dist <= 1.0 - VECTOR_MIN_SCORE)
            .order_by(dist)
            .limit(VECTOR_TOP_K)
        )
        for product, d in (await db.execute(stmt)).all():
            vector.append(ProductHit(product=product, score=float(1.0 - d), match_kind="vector"))

    merged = merge_lexical_and_vector(lexical, vector)
    return dedupe_org_wins(merged)[: max(1, limit)]
