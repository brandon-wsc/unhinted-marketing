"""Confirm-handler publish adapters (ADR 0003 / 0022). Never called from LangGraph."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from internal.config import settings
from internal.llm.keys import ByokEncryptionError, decrypt_key
from internal.media.storage import publish_url_reachability, resolve_external_url
from internal.memory import repos
from internal.memory.models import Session, SocialAccount, ToolReceipt
from schemas.contracts import DraftCopy
from schemas.tools import PublishSocialPostRequest

logger = logging.getLogger(__name__)

STUB_STATUS = "stubbed"
PUBLISHED_STATUS = "published"
FAILED_STATUS = "failed"
PUBLISH_SUCCESS_STATUSES = frozenset({STUB_STATUS, PUBLISHED_STATUS})

ERROR_TOKEN_EXPIRED = "token_expired"
ERROR_PERMISSION = "permission"
ERROR_PLATFORM = "platform_error"

# ADR 0043 §1 — reachability reason → precondition detail (fail fast, no receipt)
_REACHABILITY_DETAIL = {
    "missing": "media_url_no_base_url",
    "not_absolute": "media_url_no_base_url",
    "private_host": "media_url_not_public",
    "non_tls": "media_url_not_https",
}

_TOKEN_EXPIRED_CODES = frozenset({102, 190})
_PERMISSION_CODES = frozenset({4, 10, 200})

# Meta rejects media_publish while the container is still processing
# ('Media ID is not available', code 9007) — poll status_code to FINISHED.
_CONTAINER_READY_STATES = frozenset({"FINISHED", "PUBLISHED"})
_CONTAINER_FAILED_STATES = frozenset({"ERROR", "EXPIRED"})
_CONTAINER_POLL_SECONDS = 2.0
_CONTAINER_POLL_TIMEOUT = 45.0


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
    if isinstance(error, dict):
        raw_code = error.get("code")
        if isinstance(raw_code, int):
            code = raw_code
    if code in _TOKEN_EXPIRED_CODES or status_code in {401}:
        return ERROR_TOKEN_EXPIRED
    if code in _PERMISSION_CODES or status_code == 403:
        return ERROR_PERMISSION
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
        # Fail closed: a mistyped adapter must not silently stub a real Confirm.
        logger.error("Unknown PUBLISH_ADAPTER %r; refusing to publish", adapter)
        return PublishOutcome(
            status=FAILED_STATUS,
            platform=adapter,
            error_kind=ERROR_PLATFORM,
            message=f"Unknown PUBLISH_ADAPTER {adapter!r} — refusing to publish",
        )
    return _publish_stub()


def _publish_stub() -> PublishOutcome:
    return PublishOutcome(
        status=STUB_STATUS,
        platform="stub",
        message="Platform adapter stub — no publish performed",
    )


async def resolve_publish_image_url(
    db: AsyncSession,
    media_ids: list,
    stored_image_url: str | None,
) -> str | None:
    """External publish URL from a draft's media refs (ADR 0008 / 0024).

    Shared by Confirm and the owner/admin approve path (ADR 0041): the first
    media_id wins, else the legacy ``image_url`` stored ref.
    """
    ids = list(media_ids or [])
    if ids:
        images = await repos.get_preview_images_by_ids(db, [ids[0]])
        if images:
            url = (images[0].url or "").strip()
            if url:
                return resolve_external_url(url)
    url = (stored_image_url or "").strip()
    return resolve_external_url(url) if url else None


async def execute_publish(
    db: AsyncSession,
    *,
    session: Session,
    user_id: uuid.UUID,
    req: PublishSocialPostRequest,
    receipt: ToolReceipt | None = None,
) -> tuple[PublishOutcome, ToolReceipt]:
    """Single publish execution path for Confirm and owner/admin approve (ADR 0041).

    Same adapter call, same ``publish_social_post`` receipt write. When a parked
    ``pending_approval`` receipt is passed it is updated in place — the
    requesting member's ``user_id`` and the original ``idempotency_key`` never
    change, so approve stays idempotent end to end.
    """
    outcome = await publish_social_post(db, req, company_id=session.company_id)
    response = {
        "message": outcome.message,
        "platform": outcome.platform,
        "permalink": outcome.permalink,
        "error_kind": outcome.error_kind,
        "media_id": outcome.media_id,
    }
    if receipt is None:
        receipt = await repos.create_tool_receipt(
            db,
            session_id=session.id,
            user_id=user_id,
            tool_name=repos.PUBLISH_TOOL_NAME,
            idempotency_key=req.idempotency_key,
            status=outcome.status,
            request={
                "platform": req.platform,
                "approval_token": req.approval_token,
                "revision": req.revision,
            },
            response=response,
        )
    else:
        receipt.status = outcome.status
        merged = dict(receipt.response or {})
        merged.update(response)
        receipt.response = merged
        await db.flush()
    if outcome.status in PUBLISH_SUCCESS_STATUSES:
        session.status = "confirmed"
    return outcome, receipt


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
    reason = publish_url_reachability(image_url)
    if reason is not None:
        logger.warning("Publish image URL rejected pre-flight: reason=%s", reason)
        raise PublishPreconditionError(_REACHABILITY_DETAIL[reason])
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
        err = await _await_container_ready(client, creation_id, token)
        if err is not None:
            account.last_error_kind = err.error_kind
            return err
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
    return None, PublishOutcome(
        status=FAILED_STATUS,
        platform="instagram",
        error_kind=classify_graph_error(payload, response.status_code),
        message=_error_message(payload, response.status_code),
    )


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        parsed = response.json()
    except ValueError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _error_message(payload: dict[str, Any], status_code: int) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "")
        if message:
            return message
    return f"Instagram HTTP {status_code}"


async def _await_container_ready(
    client: httpx.AsyncClient,
    container_id: str,
    token: str,
) -> PublishOutcome | None:
    """Wait for the media container to reach FINISHED before media_publish.

    The container endpoint returns an id before Meta finishes fetching /
    processing the image; publishing immediately gets code 9007 'Media ID is
    not available'. Polls ``GET /{id}?fields=status_code`` with a bounded
    deadline; transient request failures keep polling until it lapses.
    """
    deadline = time.monotonic() + _CONTAINER_POLL_TIMEOUT
    while True:
        state = ""
        try:
            response = await client.get(
                f"{_graph_base()}/{container_id}",
                params={"fields": "status_code", "access_token": token},
            )
        except httpx.HTTPError:
            response = None
        if response is not None:
            payload = _json(response)
            state = str(payload.get("status_code") or "").upper()
            if state in _CONTAINER_READY_STATES:
                return None
            if state in _CONTAINER_FAILED_STATES:
                # Meta could not fetch/process the image — reachability of the
                # publish URL is the prime suspect (ADR 0043 §4 residual).
                return PublishOutcome(
                    status=FAILED_STATUS,
                    platform="instagram",
                    error_kind=ERROR_PLATFORM,
                    message=(
                        f"Instagram media container processing {state.lower()} — "
                        "check the publish image URL is publicly reachable"
                    ),
                )
            if not state and not response.is_success:
                return PublishOutcome(
                    status=FAILED_STATUS,
                    platform="instagram",
                    error_kind=classify_graph_error(payload, response.status_code),
                    message=_error_message(payload, response.status_code),
                )
        if time.monotonic() >= deadline:
            return PublishOutcome(
                status=FAILED_STATUS,
                platform="instagram",
                error_kind=ERROR_PLATFORM,
                message="Instagram media container not ready",
            )
        await asyncio.sleep(_CONTAINER_POLL_SECONDS)


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
