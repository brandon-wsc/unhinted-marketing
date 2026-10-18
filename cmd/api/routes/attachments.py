"""Authenticated attachment download (ADR 0047 §3).

Attachment bytes live under the ``attachments/`` object-key prefix and are
never served by the unauthenticated ``GET /api/media/{key}`` route — this is
the only read door. Access = company membership; cross-company ids 404 so the
route never leaks existence.
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

router = APIRouter(prefix="/attachments", tags=["attachments"])


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Return the original file bytes to a member of the attachment's company."""
    attachment = await db.get(Attachment, attachment_id)
    if attachment is None or not await repos.user_has_org_access(
        db, user.id, attachment.company_id
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
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(attachment.filename)}"
            ),
        },
    )
