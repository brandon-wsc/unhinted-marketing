"""Confirm-handler publish adapters (ADR 0003 / 0022). Never called from LangGraph."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from internal.config import settings
from internal.llm.keys import ByokEncryptionError, decrypt_key
from internal.memory import repos
from internal.memory.models import SocialAccount
from schemas.contracts import DraftCopy
from schemas.tools import PublishSocialPostRequest

logger = logging.getLogger(__name__)

STUB_STATUS = "stubbed"
PUBLISHED_STATUS = "published"
FAILED_STATUS = "failed"

ERROR_TOKEN_EXPIRED = "token_expired"
ERROR_PERMISSION = "permission"
ERROR_PLATFORM = "platform_error"

_TOKEN_EXPIRED_CODES = frozenset({102, 190})
_PERMISSION_CODES = frozenset({4, 10, 200})


class PublishPreconditionError(Exception):
    """Handler-mapped 400: missing account. Not a receipt-writing failure."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class PublishOutcome:
    status: str
    platform: str
    permalink: str | None = None
    error_kind: str | None = None
    media_id: str | None = None
    message: str = ""


def compose_caption(copy: DraftCopy) -> str:
    """Deterministic IG caption from the canonical draft."""
    parts: list[str] = []
    caption = (copy.caption or "").strip()
    if caption:
        parts.append(caption)
    tags: list[str] = []
    for raw in copy.hashtags or []:
        tag = raw.strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = f"#{tag}"
        tags.append(tag)
    if tags:
        parts.append(" ".join(tags))
    cta = (copy.cta or "").strip()
    if cta:
        parts.append(cta)
    return "\n\n".join(parts)


def _graph_base() -> str:
    version = (settings.meta_graph_api_version or "v22.0").strip().lstrip("/")
    return f"https://graph.instagram.com/{version}"


def classify_graph_error(payload: dict[str, Any] | None, status_code: int) -> str:
    error = (payload or {}).get("error") if isinstance(payload, dict) else None
    code: int | None = None
    err_type = ""
    if isinstance(error, dict):
        raw_code = error.get("code")
        if isinstance(raw_code, int):
            code = raw_code
        err_type = str(error.get("type") or "")
    if code in _TOKEN_EXPIRED_CODES or status_code in {401}:
        return ERROR_TOKEN_EXPIRED
    if code in _PERMISSION_CODES or status_code == 403:
        return ERROR_PERMISSION
    if err_type == "OAuthException" and status_code in {400, 401}:
        return ERROR_TOKEN_EXPIRED
    return ERROR_PLATFORM


def _token_expired(account: SocialAccount, now: datetime | None = None) -> bool:
    if account.expires_at is None:
        return False
    stamp = now or datetime.now(UTC)
    expires = account.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires <= stamp


async def publish_social_post(
    db: AsyncSession,
    req: PublishSocialPostRequest,
    *,
    company_id: uuid.UUID,
) -> PublishOutcome:
    adapter = (settings.publish_adapter or "stub").strip().lower()
    if adapter == "instagram":
        return await _publish_instagram(db, req, company_id=company_id)
    if adapter not in {"stub", ""}:
        logger.warning("Unknown PUBLISH_ADAPTER %r; using stub", adapter)
    return _publish_stub()


def _publish_stub() -> PublishOutcome:
    return PublishOutcome(
        status=STUB_STATUS,
        platform="stub",
        message="Platform adapter stub — no publish performed",
    )


async def _publish_instagram(
    db: AsyncSession,
    req: PublishSocialPostRequest,
    *,
    company_id: uuid.UUID,
) -> PublishOutcome:
    account = await repos.get_social_account(db, company_id, "instagram")
    if account is None or not repos.social_account_is_connected(account):
        raise PublishPreconditionError("social_account_not_connected")
    if _token_expired(account):
        account.last_error_kind = ERROR_TOKEN_EXPIRED
        return PublishOutcome(
            status=FAILED_STATUS,
            platform="instagram",
            error_kind=ERROR_TOKEN_EXPIRED,
            message="Instagram token expired",
        )
    image_url = (req.image_url or "").strip()
    if not image_url.startswith("http://") and not image_url.startswith("https://"):
        return PublishOutcome(
            status=FAILED_STATUS,
            platform="instagram",
            error_kind=ERROR_PLATFORM,
            message="Publish image URL is not publicly reachable",
        )
    try:
        token = decrypt_key(account.access_token_encrypted)
    except ByokEncryptionError:
        account.last_error_kind = ERROR_PLATFORM
        return PublishOutcome(
            status=FAILED_STATUS,
            platform="instagram",
            error_kind=ERROR_PLATFORM,
            message="Could not decrypt the stored Instagram token",
        )

    caption = compose_caption(req.draft_copy)
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        container, err = await _graph_post(
            client,
            f"{_graph_base()}/{account.ig_user_id}/media",
            data={
                "image_url": image_url,
                "caption": caption,
                "access_token": token,
            },
        )
        if err is not None:
            account.last_error_kind = err.error_kind
            return err
        creation_id = str((container or {}).get("id") or "").strip()
        if not creation_id:
            account.last_error_kind = ERROR_PLATFORM
            return PublishOutcome(
                status=FAILED_STATUS,
                platform="instagram",
                error_kind=ERROR_PLATFORM,
                message="Graph media container response missing id",
            )
        published, err = await _graph_post(
            client,
            f"{_graph_base()}/{account.ig_user_id}/media_publish",
            data={"creation_id": creation_id, "access_token": token},
        )
        if err is not None:
            account.last_error_kind = err.error_kind
            return err
        media_id = str((published or {}).get("id") or "").strip()
        permalink: str | None = None
        if media_id:
            permalink = await _fetch_permalink(client, media_id, token)

    account.last_error_kind = None
    account.last_verified_at = datetime.now(UTC)
    return PublishOutcome(
        status=PUBLISHED_STATUS,
        platform="instagram",
        permalink=permalink,
        media_id=media_id or None,
        message="Published to Instagram",
    )


async def _graph_post(
    client: httpx.AsyncClient,
    url: str,
    *,
    data: dict[str, str],
) -> tuple[dict[str, Any] | None, PublishOutcome | None]:
    try:
        response = await client.post(url, data=data)
    except httpx.TimeoutException:
        return None, PublishOutcome(
            status=FAILED_STATUS,
            platform="instagram",
            error_kind=ERROR_PLATFORM,
            message="Instagram request timed out",
        )
    except httpx.HTTPError:
        return None, PublishOutcome(
            status=FAILED_STATUS,
            platform="instagram",
            error_kind=ERROR_PLATFORM,
            message="Instagram request failed",
        )
    payload: dict[str, Any] = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            payload = parsed
    except ValueError:
        payload = {}
    if response.is_success:
        return payload, None
    kind = classify_graph_error(payload, response.status_code)
    message = ""
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "")
    return None, PublishOutcome(
        status=FAILED_STATUS,
        platform="instagram",
        error_kind=kind,
        message=message or f"Instagram HTTP {response.status_code}",
    )


async def _fetch_permalink(
    client: httpx.AsyncClient, media_id: str, token: str
) -> str | None:
    try:
        response = await client.get(
            f"{_graph_base()}/{media_id}",
            params={"fields": "permalink", "access_token": token},
        )
        if not response.is_success:
            return None
        payload = response.json()
        if isinstance(payload, dict):
            permalink = payload.get("permalink")
            if isinstance(permalink, str) and permalink.strip():
                return permalink.strip()
    except (httpx.HTTPError, ValueError):
        return None
    return None
