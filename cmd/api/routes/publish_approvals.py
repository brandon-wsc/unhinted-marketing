"""Publish approval queue — member Confirm parks for owner/admin review (ADR 0041).

Traditional HTTP, mirroring the product-proposal approve/reject plane
(ADR 0011): sessions stay user-scoped, so the queue payload carries
everything needed to render the approval card and to execute the parked
publish — including the draft's own ``approval_token``. Approve runs the
same ``execute_publish`` path as ``POST /sessions/{id}/confirm``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.auth.org import require_company_settings_editor
from internal.media.storage import resolve_stored_url
from internal.memory import repos
from internal.memory.database import get_db
from internal.memory.models import ToolReceipt, User
from internal.session.events import session_event_bus
from internal.session.media import media_item_payload
from internal.session.service import DEFAULT_PLATFORM
from internal.tools.publish import (
    PUBLISH_SUCCESS_STATUSES,
    PublishPreconditionError,
    execute_publish,
    resolve_publish_image_url,
)
from schemas.company import PublishApprovalItem, PublishApprovalListResponse
from schemas.contracts import DraftCopy, PreviewMediaItem
from schemas.tools import PublishSocialPostRequest

router = APIRouter(prefix="/companies", tags=["companies"])


def _request_media_ids(request: dict) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for raw in request.get("media_ids") or []:
        try:
            ids.append(uuid.UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    return ids


def _reviewed_at(response: dict) -> datetime | None:
    raw = response.get("reviewed_at")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


async def _approval_item(
    db: AsyncSession, receipt: ToolReceipt, requester: User | None
) -> PublishApprovalItem:
    request = receipt.request if isinstance(receipt.request, dict) else {}
    response = receipt.response if isinstance(receipt.response, dict) else {}

    media: list[PreviewMediaItem] = []
    media_ids = _request_media_ids(request)
    if media_ids:
        images = await repos.get_preview_images_by_ids(db, media_ids)
        by_id = {img.id: img for img in images}
        for mid in media_ids:
            img = by_id.get(mid)
            if img is None:
                continue
            media.append(
                PreviewMediaItem.model_validate(
                    media_item_payload(
                        image_id=img.id,
                        url=img.url,
                        plan=img.plan,
                        format=img.format,
                        role=img.role,
                        seq=img.seq,
                        status=img.status,
                    )
                )
            )
    stored = request.get("image_url")
    image_url = resolve_stored_url(stored) if isinstance(stored, str) else None
    if image_url is None and media:
        image_url = media[0].url

    copy = request.get("copy")
    permalink = response.get("permalink")
    error_kind = response.get("error_kind")
    reviewed_by_email = response.get("reviewed_by_email")
    return PublishApprovalItem(
        id=receipt.id,
        session_id=session_id_of(receipt),
        user_id=receipt.user_id,
        requested_by_email=requester.email if requester else None,
        requested_by_name=requester.display_name if requester else None,
        platform=str(request.get("platform") or DEFAULT_PLATFORM),
        revision=int(request.get("revision") or 0),
        draft_copy=DraftCopy.model_validate(copy) if isinstance(copy, dict) else DraftCopy(),
        media=media,
        image_url=image_url,
        status=receipt.status,
        idempotency_key=receipt.idempotency_key,
        permalink=permalink if isinstance(permalink, str) else None,
        error_kind=error_kind if isinstance(error_kind, str) else None,
        created_at=receipt.created_at,
        reviewed_at=_reviewed_at(response),
        reviewed_by_email=reviewed_by_email if isinstance(reviewed_by_email, str) else None,
    )


def session_id_of(receipt: ToolReceipt) -> uuid.UUID:
    assert receipt.session_id is not None  # publish receipts always bind a session
    return receipt.session_id


async def _publish_confirm_event(receipt: ToolReceipt) -> None:
    response = receipt.response if isinstance(receipt.response, dict) else {}
    await session_event_bus.publish(
        session_id_of(receipt),
        "confirm.completed",
        {
            "receipt_id": str(receipt.id),
            "status": receipt.status,
            "tool_name": receipt.tool_name,
            "idempotency_key": receipt.idempotency_key,
            "permalink": response.get("permalink"),
            "error_kind": response.get("error_kind"),
        },
    )


def _stamp_reviewed(receipt: ToolReceipt, reviewer: User) -> None:
    merged = dict(receipt.response or {})
    merged["reviewed_by_email"] = reviewer.email
    merged["reviewed_at"] = datetime.now(UTC).isoformat()
    receipt.response = merged


@router.get(
    "/{company_id}/publish-approvals",
    response_model=PublishApprovalListResponse,
)
async def list_publish_approvals(
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublishApprovalListResponse:
    """Owner/admin queue: member publish requests parked by the org policy."""
    rows = await repos.list_pending_publish_approvals(db, company_id)
    return PublishApprovalListResponse(
        company_id=company_id,
        items=[
            await _approval_item(db, receipt, requester) for receipt, _session, requester in rows
        ],
    )


@router.post(
    "/{company_id}/publish-approvals/{receipt_id}/approve",
    response_model=PublishApprovalItem,
)
async def approve_publish_request(
    receipt_id: uuid.UUID,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublishApprovalItem:
    """Execute the parked publish through the Confirm code path (ADR 0041).

    The parked draft's ``approval_token`` executes as-is — approve neither
    mints a token nor bypasses token validation. The member's ``user_id``
    and original ``idempotency_key`` stay on the receipt, so a repeat
    approve replays the same row instead of publishing twice.
    """
    row = await repos.get_publish_approval_receipt(db, company_id, receipt_id, for_update=True)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found"
        )
    receipt, session = row
    requester = await db.get(User, receipt.user_id)
    if receipt.status in PUBLISH_SUCCESS_STATUSES:
        # Idempotent replay — the adapter already ran for this receipt.
        return await _approval_item(db, receipt, requester)
    if receipt.status != repos.PUBLISH_PENDING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approval request is not pending",
        )

    request = receipt.request if isinstance(receipt.request, dict) else {}
    approval_token = request.get("approval_token")
    if not isinstance(approval_token, str) or not approval_token.strip():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approval request payload is incomplete",
        )
    req = PublishSocialPostRequest(
        session_id=session.id,
        approval_token=approval_token,
        idempotency_key=receipt.idempotency_key,
        platform=str(request.get("platform") or DEFAULT_PLATFORM),
        draft_copy=DraftCopy.model_validate(request.get("copy") or {}),
        image_url=await resolve_publish_image_url(
            db, _request_media_ids(request), request.get("image_url")
        ),
        revision=int(request.get("revision") or 0),
    )
    try:
        _outcome, receipt = await execute_publish(
            db, session=session, user_id=receipt.user_id, req=req, receipt=receipt
        )
    except PublishPreconditionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.detail,
        ) from exc
    _stamp_reviewed(receipt, user)
    await db.flush()
    await db.commit()
    await db.refresh(receipt)
    await _publish_confirm_event(receipt)
    return await _approval_item(db, receipt, requester)


@router.post(
    "/{company_id}/publish-approvals/{receipt_id}/reject",
    response_model=PublishApprovalItem,
)
async def reject_publish_request(
    receipt_id: uuid.UUID,
    company_id: Annotated[uuid.UUID, Depends(require_company_settings_editor)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublishApprovalItem:
    """Reject → member can edit the draft and Confirm again (re-parks)."""
    row = await repos.get_publish_approval_receipt(db, company_id, receipt_id, for_update=True)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found"
        )
    receipt, _session = row
    requester = await db.get(User, receipt.user_id)
    if receipt.status == repos.PUBLISH_REJECTED:
        return await _approval_item(db, receipt, requester)
    if receipt.status != repos.PUBLISH_PENDING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approval request is not pending",
        )
    receipt.status = repos.PUBLISH_REJECTED
    _stamp_reviewed(receipt, user)
    await db.flush()
    await db.commit()
    await db.refresh(receipt)
    await _publish_confirm_event(receipt)
    return await _approval_item(db, receipt, requester)
