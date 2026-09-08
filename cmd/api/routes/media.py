"""Public media bytes (ADR 0024).

Unauthenticated so ``<img src>`` and Instagram Graph can fetch. Object keys
include a session UUID; signed URLs stay later hardening. Cloud stores serve
from S3 directly — this route only streams the on-prem local store.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from internal.media.backends import MediaStorageError
from internal.media.storage import local_media_path

router = APIRouter(tags=["media"])

_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _media_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


@router.get("/media/{key:path}")
async def get_media(key: str) -> FileResponse:
    try:
        path = local_media_path(key)
    except MediaStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        ) from exc
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return FileResponse(path, media_type=_media_type(path))
