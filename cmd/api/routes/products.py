"""Company product catalog routes (knowledge COLLECT K3/K3b)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.auth.org import (
    COMPANY_SETTINGS_EDITOR_ROLES,
    require_company_access,
    require_company_settings_editor,
)
from internal.memory.database import get_db
from internal.memory.embeddings import embed_texts
from internal.memory.models import User
from internal.memory.product_import import parse_product_upload
from internal.memory.repos import (
    archive_product,
    create_manual_product,
    get_org_membership,
    get_product,
    list_org_skus,
    list_products,
    upsert_product_row,
)
from schemas.company import (
    ProductCreateRequest,
    ProductImportResponse,
    ProductItem,
    ProductListResponse,
)

router = APIRouter(prefix="/companies", tags=["companies"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _parse_scope(raw: str) -> Literal["org", "user"]:
    if raw == "user":
        return "user"
    if raw == "org":
        return "org"
    raise HTTPException(status_code=400, detail="scope must be org or user")


def _profile_strings(profile: dict | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (profile or {}).items():
        if value is None:
            continue
        out[str(key)] = value if isinstance(value, str) else str(value)
    return out


def _to_item(row, *, covered: bool = False) -> ProductItem:
    return ProductItem(
        id=row.id,
        sku=row.sku,
        name=row.name,
        status=row.status,
        owner_scope=row.owner_scope,
        covered_by_company=covered,
        profile=_profile_strings(row.profile),
        updated_at=row.updated_at,
    )


@router.get("/{company_id}/products", response_model=ProductListResponse)
async def list_company_products(
    company_id: Annotated[uuid.UUID, Depends(require_company_access)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    scope: Annotated[str, Query()] = "org",
) -> ProductListResponse:
    owner_scope = _parse_scope(scope)
    membership = await get_org_membership(db, user.id, company_id)
    if owner_scope == "org":
        can_edit = bool(membership and membership.role in COMPANY_SETTINGS_EDITOR_ROLES)
        rows = await list_products(db, company_id=company_id, owner_scope="org")
        items = [_to_item(r) for r in rows]
    else:
        can_edit = True  # any member manages their personal library
        rows = await list_products(
            db, company_id=company_id, owner_scope="user", user_id=user.id
        )
        org_skus = await list_org_skus(db, company_id=company_id)
        items = [_to_item(r, covered=r.sku in org_skus) for r in rows]

    return ProductListResponse(
        company_id=company_id,
        scope=owner_scope,
        items=items,
        can_edit=can_edit,
    )


@router.post("/{company_id}/products/import", response_model=ProductImportResponse)
async def import_company_products(
    company_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    scope: Annotated[str, Query()] = "org",
) -> ProductImportResponse:
    owner_scope = _parse_scope(scope)
    if owner_scope == "org":
        await require_company_settings_editor(company_id, user, db)
        user_id = None
    else:
        await require_company_access(company_id, user, db)
        user_id = user.id

    filename = file.filename or "upload.csv"
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")

    parsed, parse_errors = parse_product_upload(filename, data)
    if not parsed and parse_errors:
        raise HTTPException(status_code=400, detail=parse_errors[0])

    imported = 0
    updated = 0
    docs = [row["search_document"] for row in parsed]
    embeddings = embed_texts(docs)
    for row, emb in zip(parsed, embeddings, strict=True):
        _, created = await upsert_product_row(
            db,
            company_id=company_id,
            owner_scope=owner_scope,
            user_id=user_id,
            sku=row["sku"],
            name=row["name"],
            search_document=row["search_document"],
            profile=row["profile"],
            embedding=emb,
            embed=False,
        )
        if created:
            imported += 1
        else:
            updated += 1

    await db.commit()
    return ProductImportResponse(
        imported=imported,
        updated=updated,
        skipped=len(parse_errors),
        errors=parse_errors[:50],
    )


@router.post("/{company_id}/products", response_model=ProductItem, status_code=status.HTTP_201_CREATED)
async def create_company_product(
    body: ProductCreateRequest,
    company_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    scope: Annotated[str, Query()] = "user",
) -> ProductItem:
    """Manual add — personal library by default (Mine tab)."""
    owner_scope = _parse_scope(scope)
    if owner_scope == "org":
        await require_company_settings_editor(company_id, user, db)
        user_id = None
    else:
        await require_company_access(company_id, user, db)
        user_id = user.id

    row, _ = await create_manual_product(
        db,
        company_id=company_id,
        owner_scope=owner_scope,
        user_id=user_id,
        sku=body.sku,
        name=body.name,
        notes=body.notes,
    )
    await db.commit()
    await db.refresh(row)
    covered = False
    if owner_scope == "user":
        org_skus = await list_org_skus(db, company_id=company_id)
        covered = row.sku in org_skus
    return _to_item(row, covered=covered)


@router.post("/{company_id}/products/{product_id}/archive", response_model=ProductItem)
async def archive_company_product(
    product_id: uuid.UUID,
    company_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProductItem:
    await require_company_access(company_id, user, db)
    row = await get_product(db, company_id=company_id, product_id=product_id)
    if not row or row.status != "active":
        raise HTTPException(status_code=404, detail="Product not found")

    if row.owner_scope == "org":
        await require_company_settings_editor(company_id, user, db)
    elif row.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    await archive_product(db, row)
    await db.commit()
    await db.refresh(row)
    return _to_item(row)
