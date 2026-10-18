"""Authenticated attachment download + save-to-library (ADR 0047 §2/§3).

Attachment bytes live under the ``attachments/`` object-key prefix and are
never served by the unauthenticated ``GET /api/media/{key}`` route — this is
the only read door. Access = company membership; cross-company ids 404 so the
route never leaks existence. 「存入我嘅庫」is an explicit HTTP action here —
chat can never commit a document (ADR 0011).
"""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.media.storage import MediaStorageError, get_bytes
from internal.memory import repos
from internal.memory.database import get_db
from internal.memory.models import Attachment, User
from schemas.session import AttachmentOut

router = APIRouter(prefix="/attachments", tags=["attachments"])


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Return the original file bytes — ADR 0047 §3 owner matrix.

    ``org`` rows serve any company member; ``session``/``user`` rows are the
    uploader's alone — company membership must not hand a colleague someone
    else's scratch or Mine file. Every refusal is a uniform 404.
    """
    attachment = await db.get(Attachment, attachment_id)
    if (
        attachment is None
        or not await repos.user_has_org_access(db, user.id, attachment.company_id)
        or (attachment.owner_scope != "org" and attachment.user_id != user.id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
    try:
        data = await get_bytes(attachment.object_key)
    except (MediaStorageError, ClientError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found") from exc
    return Response(
        content=data,
        media_type=attachment.content_type,
        headers={
            # RFC 5987 filename* — filenames are user-controlled.
            "Content-Disposition": (f"attachment; filename*=UTF-8''{quote(attachment.filename)}"),
        },
    )


@router.post("/{attachment_id}/save", response_model=AttachmentOut)
async def save_attachment(
    attachment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AttachmentOut:
    """「存入我嘅庫」(ADR 0047 §2) — flip the caller's own scratch row to Mine.

    Owner-only: ``session``/``user`` rows save for their uploader alone —
    a same-company member cannot save another member's scratch, and every
    refusal is a uniform 404 so existence never leaks. Re-saving an
    already-user-scope row is a 200 no-op (idempotent).
    """
    attachment = await db.get(Attachment, attachment_id)
    if (
        attachment is None
        or not await repos.user_has_org_access(db, user.id, attachment.company_id)
        or attachment.owner_scope not in ("session", "user")
        or attachment.user_id != user.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
    if attachment.owner_scope == "session":
        attachment.owner_scope = "user"
        # Detach from the origin session: the ``session_id`` FK cascade would
        # otherwise kill this now-library row when the session is deleted.
        # attachment_sessions join rows stay — the session keeps referencing
        # the file for digests and shares the GC refcount (§13).
        attachment.session_id = None
    await db.commit()
    return AttachmentOut.model_validate(attachment)
