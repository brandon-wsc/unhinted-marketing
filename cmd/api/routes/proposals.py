"""Mine → org product proposals (knowledge K6 / ADR 0011)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.auth.org import require_company_access, require_company_settings_editor
from internal.memory.database import get_db
from internal.memory.models import ProductProposal, User
from internal.memory.product_import import build_search_document
from internal.memory.repos import (
    create_product_proposal,
    get_org_product_by_sku,
    get_pending_proposal_by_sku,
    get_product,
    get_product_proposal,
    list_product_proposals,
    mark_proposal_reviewed,
    upsert_product_row,
)
from schemas.company import (
    ProductProposalFieldDiff,
    ProductProposalItem,
    ProductProposalListResponse,
)

router = APIRouter(prefix="/companies", tags=["companies"])


def _profile_strings(profile: dict | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (profile or {}).items():
        if value is None:
            continue
        out[str(key)] = value if isinstance(value, str) else str(value)
    return out


def _field_diff(
    current: dict[str, str], proposed: dict[str, str]
) -> list[ProductProposalFieldDiff]:
    keys = sorted(set(current) | set(proposed))
    rows: list[ProductProposalFieldDiff] = []
    for key in keys:
        cur = current.get(key)
        prop = proposed.get(key)
        if cur is None and prop is not None:
            change = "added"
        elif prop is None and cur is not None:
            change = "removed"
        elif cur != prop:
            change = "changed"
        else:
            change = "same"
        rows.append(
            ProductProposalFieldDiff(key=key, current=cur, proposed=prop, change=change)
        )
    return rows


async def _emails_for(db: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = [uid for uid in user_ids if uid is not None]
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.email).where(User.id.in_(ids)))
    return {uid: email for uid, email in rows.all()}


async def _to_item(
    db: AsyncSession,
    proposal: ProductProposal,
    *,
    emails: dict[uuid.UUID, str] | None = None,
) -> ProductProposalItem:
    proposed = _profile_strings(proposal.profile)
    org_row = await get_org_product_by_sku(
        db, company_id=proposal.company_id, sku=proposal.sku
    )
    current = _profile_strings(org_row.profile if org_row else None)
    proposer_ids = [proposal.proposed_by] if proposal.proposed_by else []
    email_map = emails if emails is not None else await _emails_for(db, proposer_ids)
    allowed = {"pending", "approved", "rejected"}
    reviewed_status = proposal.status if proposal.status in allowed else "pending"
    return ProductProposalItem(
        id=proposal.id,
        company_id=proposal.company_id,
        sku=proposal.sku,
        name=proposal.name,
        status=reviewed_status,
        proposed_by=proposal.proposed_by,
        proposed_by_email=(
            email_map.get(proposal.proposed_by) if proposal.proposed_by else None
        ),
        source_product_id=proposal.source_product_id,
        profile=proposed,
        current_name=org_row.name if org_row else None,
        current_profile=current,
        fields=_field_diff(current, proposed),
        created_at=proposal.created_at,
        reviewed_at=proposal.reviewed_at,
    )


@router.post(
    "/{company_id}/products/{product_id}/propose",
    response_model=ProductProposalItem,
    status_code=status.HTTP_201_CREATED,
)
async def propose_product(
    product_id: uuid.UUID,
    company_id: Annotated[uuid.UUID, Depends(require_company_access)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProductProposalItem:
    row = await get_product(db, company_id=company_id, product_id=product_id)
    if not row or row.status != "active":
        raise HTTPException(status_code=404, detail="Product not found")
    if row.owner_scope != "user" or row.user_id != user.id:
        raise HTTPException(status_code=403, detail="Only your Mine products can be proposed")
    existing = await get_pending_proposal_by_sku(db, company_id=company_id, sku=row.sku)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending proposal already exists for this product code",
        )
    try:
        proposal = await create_product_proposal(
            db, company_id=company_id, source_product=row, proposed_by=user.id
        )
        await db.commit()
        await db.refresh(proposal)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending proposal already exists for this product code",
        ) from None
    return await _to_item(db, proposal)


@router.get("/{company_id}/proposals", response_model=ProductProposalListResponse)
async def list_company_proposals(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[str, Query(alias="status")] = "pending",
) -> ProductProposalListResponse:
    if status_filter not in {"pending", "approved", "rejected"}:
        raise HTTPException(status_code=400, detail="status must be pending, approved, or rejected")
    rows = await list_product_proposals(db, company_id=company_id, status=status_filter)
    emails = await _emails_for(db, [r.proposed_by for r in rows if r.proposed_by])
    items = [await _to_item(db, row, emails=emails) for row in rows]
    return ProductProposalListResponse(company_id=company_id, items=items)


@router.post("/{company_id}/proposals/{proposal_id}/approve", response_model=ProductProposalItem)
async def approve_product_proposal(
    proposal_id: uuid.UUID,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProductProposalItem:
    proposal = await get_product_proposal(db, company_id=company_id, proposal_id=proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status == "approved":
        return await _to_item(db, proposal)
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail="Proposal is not pending")

    profile = _profile_strings(proposal.profile)
    search_document = build_search_document(profile, sku=proposal.sku, name=proposal.name)
    await upsert_product_row(
        db,
        company_id=company_id,
        owner_scope="org",
        user_id=None,
        sku=proposal.sku,
        name=proposal.name,
        search_document=search_document,
        profile=profile,
    )
    await mark_proposal_reviewed(db, proposal, status="approved", reviewed_by=user.id)
    await db.commit()
    await db.refresh(proposal)
    return await _to_item(db, proposal)


@router.post("/{company_id}/proposals/{proposal_id}/reject", response_model=ProductProposalItem)
async def reject_product_proposal(
    proposal_id: uuid.UUID,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProductProposalItem:
    proposal = await get_product_proposal(db, company_id=company_id, proposal_id=proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status == "rejected":
        return await _to_item(db, proposal)
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail="Proposal is not pending")
    await mark_proposal_reviewed(db, proposal, status="rejected", reviewed_by=user.id)
    await db.commit()
    await db.refresh(proposal)
    return await _to_item(db, proposal)
