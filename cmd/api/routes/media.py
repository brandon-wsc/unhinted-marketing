"""Unauthenticated local-store download (ADR 0024). S3 objects use the public/CDN URL."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from internal.media.storage import (
    MediaStorageError,
    local_abs_path,
    local_read_grace,
    media_backend,
)

router = APIRouter(tags=["media"])

_EXT_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


@router.get("/media/{key:path}")
async def get_media(key: str) -> FileResponse:
    try:
        if media_backend() != "local" and not local_read_grace():
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
        path = local_abs_path(key)
    except MediaStorageError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found") from exc
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
    ext = path.suffix.lstrip(".").lower()
    media_type = _EXT_CONTENT_TYPES.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media_type)
