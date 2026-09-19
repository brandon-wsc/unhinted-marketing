"""Instagram Login OAuth for org connect (ADR 0022 OAuth slice).

Authorization-code flow against ``https://www.instagram.com/oauth/authorize``.
The callback is a public route (Meta redirects there with no Authorization header), so the
org is recovered from the signed ``state`` and the browser round-trip is protected with a
double-submit CSRF cookie set at ``start`` time and verified at the callback.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from internal.config import settings
from internal.llm.keys import ByokEncryptionError, decrypt_key, encrypt_key, mask_key
from internal.memory import repos
from internal.memory.models import SocialAccount

# Scopes for Instagram Content Publishing via Business Login for Instagram.
META_OAUTH_SCOPES = "instagram_business_basic,instagram_business_content_publish"
PUBLISH_SCOPE = "instagram_business_content_publish"
_PROFESSIONAL_TYPES = frozenset({"BUSINESS", "MEDIA_CREATOR", "CREATOR"})

DIALOG_PATH = "https://www.instagram.com/oauth/authorize"
SHORT_LIVED_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
LONG_LIVED_TOKEN_URL = "https://graph.instagram.com/access_token"
ME_URL = "https://graph.instagram.com/v{version}/me"
ME_FIELDS = "user_id,id,username,account_type"

logger = logging.getLogger(__name__)

OAUTH_MAX_AGE_DAYS = 1
# Abandoned connect (Instagram never hits the callback) should not stay "pending" forever.
OAUTH_PENDING_TTL = timedelta(minutes=10)
CSRF_COOKIE = "meta_oauth_csrf"


class MetaOAuthError(Exception):
    """User-facing connect failure (mapped to HTTP 4xx by the routes)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class OAuthStart:
    authorization_url: str
    connect_state: str  # encrypted blob to persist on the social_accounts row
    csrf_token: str  # also set as a double-submit cookie by the route


@dataclass(frozen=True)
class OAuthTokenResult:
    access_token: str
    fb_user_id: str
    ig_user_id: str
    expires_at: datetime | None
    missing_scopes: list[str]


def _graph_version() -> str:
    return (settings.meta_graph_api_version or "v22.0").strip().lstrip("/v")


_CALLBACK_PATH = "/api/social/oauth/callback"


def _oauth_redirect_uri() -> str:
    """Exact URI Meta must whitelist — `{web_base_url}/api/social/oauth/callback`."""
    from internal.instance.config import get_snapshot

    base = (get_snapshot().web_base_url or "").strip().rstrip("/")
    if not base:
        raise MetaOAuthError("meta_oauth_not_configured")
    return f"{base}{_CALLBACK_PATH}"


def _oauth_fields(redirect_uri: str | None = None) -> dict[str, str]:
    if not settings.meta_app_id or not settings.meta_app_secret:
        raise MetaOAuthError("meta_oauth_not_configured")
    return {
        "client_id": settings.meta_app_id,
        "client_secret": settings.meta_app_secret,
        "redirect_uri": redirect_uri or _oauth_redirect_uri(),
    }


def _encrypt_connect_state(row_id: str, csrf_token: str, redirect_uri: str) -> str:
    try:
        return encrypt_key(
            json.dumps(
                {
                    "row_id": row_id,
                    "csrf_token": csrf_token,
                    # Meta requires the exchange redirect_uri to equal the
                    # authorize-time one; pin it so a mid-flow web_base_url
                    # edit cannot mismatch.
                    "redirect_uri": redirect_uri,
                    "started_at": datetime.now(UTC).isoformat(),
                }
            )
        )
    except ByokEncryptionError as exc:
        raise MetaOAuthError("meta_oauth_key_unavailable") from exc


def _decrypt_connect_state(stored: str) -> dict[str, str] | None:
    try:
        payload = json.loads(decrypt_key(stored))
    except (ByokEncryptionError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    row_id = str(payload.get("row_id") or "")
    csrf_token = str(payload.get("csrf_token") or "")
    if not row_id or not csrf_token:
        return None
    return payload


def pending_connect_is_stale(blob: str, *, now: datetime | None = None) -> bool:
    """True when the encrypted pending blob is missing, undecryptable, or too old."""
    payload = _decrypt_connect_state(blob)
    if payload is None:
        return True
    raw = str(payload.get("started_at") or "")
    if not raw:
        return False
    try:
        started = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - started > OAUTH_PENDING_TTL


def _state_value(row_id: str, token: str) -> str:
    return f"{row_id}:{token}"


def parse_state(state: str) -> tuple[str, str] | None:
    """Return (row_id, encrypted blob) when the state value looks like ours."""
    try:
        row_id, token = state.split(":", 1)
    except ValueError:
        return None
    if not row_id or not token:
        return None
    return row_id, token


async def start_oauth(db: AsyncSession, *, company_id: uuid.UUID) -> OAuthStart:
    """Create the dialog URL + persist the encrypted pending state + CSRF token.

    Caller owns the transaction (commit on success, rollback on failure).
    """
    fields = _oauth_fields()
    csrf_token = secrets.token_urlsafe(32)
    row = await repos.get_social_account(db, company_id, "instagram")
    if row is None:
        row = SocialAccount(
            company_id=company_id,
            platform="instagram",
            ig_user_id="",
            access_token_encrypted="",
            token_last4="",
            created_by=None,
        )
        db.add(row)
        await db.flush()
    blob = _encrypt_connect_state(str(row.id), csrf_token, fields["redirect_uri"])
    row.oauth_connect_state = blob
    state = _state_value(str(row.id), blob)
    params = {
        "client_id": fields["client_id"],
        "redirect_uri": fields["redirect_uri"],
        "scope": META_OAUTH_SCOPES,
        "state": state,
        "response_type": "code",
    }
    return OAuthStart(
        authorization_url=f"{DIALOG_PATH}?{urlencode(params)}",
        connect_state=blob,
        csrf_token=csrf_token,
    )


async def exchange_code(
    db: AsyncSession,
    *,
    code: str,
    state: str,
    csrf_token: str | None,
) -> OAuthTokenResult:
    """Exchange the auth code for a long-lived IG user token and upsert the account.

    ``csrf_token`` is the double-submit cookie value; it must match the value
    embedded in the encrypted state blob (proves the same browser started it).
    Caller owns the transaction (commit on success, rollback on failure).
    """
    parsed = parse_state(state)
    if parsed is None:
        raise MetaOAuthError("meta_oauth_invalid_state")
    row_id_str, _ = parsed
    try:
        row_uuid = uuid.UUID(row_id_str)
    except ValueError:
        raise MetaOAuthError("meta_oauth_invalid_state") from None
    row = await repos.get_social_account_by_id(db, row_uuid)
    if row is None or not row.oauth_connect_state:
        raise MetaOAuthError("meta_oauth_no_pending_connect")
    payload = _decrypt_connect_state(row.oauth_connect_state)
    if payload is None:
        raise MetaOAuthError("meta_oauth_no_pending_connect")
    stored_row_id = str(payload.get("row_id") or "")
    stored_csrf = str(payload.get("csrf_token") or "")
    if stored_row_id != row_id_str:
        raise MetaOAuthError("meta_oauth_invalid_state")
    if not stored_csrf or stored_csrf != (csrf_token or ""):
        raise MetaOAuthError("meta_oauth_csrf_mismatch")

    fields = _oauth_fields(redirect_uri=str(payload.get("redirect_uri") or "") or None)
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        token_resp = await client.post(
            SHORT_LIVED_TOKEN_URL,
            data={
                "client_id": fields["client_id"],
                "client_secret": fields["client_secret"],
                "grant_type": "authorization_code",
                "redirect_uri": fields["redirect_uri"],
                "code": code,
            },
        )
        token_payload = _json(token_resp)
        if not token_resp.is_success:
            raise MetaOAuthError(_graph_error_hint(token_payload, token_resp.status_code))
        short_token, _, granted_scopes = _parse_short_lived(token_payload)
        if not short_token:
            raise MetaOAuthError("meta_oauth_exchange_failed")

        long_resp = await client.get(
            LONG_LIVED_TOKEN_URL,
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": fields["client_secret"],
                "access_token": short_token,
            },
        )
        long_payload = _json(long_resp)
        if not long_resp.is_success:
            raise MetaOAuthError(_graph_error_hint(long_payload, long_resp.status_code))
        access_token = str(long_payload.get("access_token") or "")
        if not access_token:
            raise MetaOAuthError("meta_oauth_exchange_failed")
        expires_at: datetime | None = None
        raw_expires_in = long_payload.get("expires_in")
        if isinstance(raw_expires_in, (int, float)):
            expires_at = datetime.now(UTC) + timedelta(seconds=float(raw_expires_in))

        me_resp = await client.get(
            ME_URL.format(version=_graph_version()),
            params={"fields": ME_FIELDS, "access_token": access_token},
        )
        me_payload = _json(me_resp)
        if not me_resp.is_success:
            raise MetaOAuthError(_graph_error_hint(me_payload, me_resp.status_code))

        account_type = str(me_payload.get("account_type") or "").upper()
        if account_type == "PERSONAL":
            raise MetaOAuthError("meta_oauth_not_professional")
        if account_type and account_type not in _PROFESSIONAL_TYPES:
            raise MetaOAuthError("meta_oauth_not_professional")

        ig_user_id = (
            str(me_payload.get("user_id") or "").strip() or str(me_payload.get("id") or "").strip()
        )
        if not ig_user_id:
            logger.warning(
                "meta oauth no ig user granted=%s account_type=%s",
                granted_scopes,
                account_type,
            )
            raise MetaOAuthError("meta_oauth_not_professional")

        if PUBLISH_SCOPE not in granted_scopes:
            raise MetaOAuthError("meta_oauth_missing_publish")

    required = {s.strip() for s in META_OAUTH_SCOPES.split(",") if s.strip()}
    missing_scopes = [s for s in sorted(required) if granted_scopes and s not in granted_scopes]

    await repos.upsert_social_account(
        db,
        company_id=row.company_id,
        platform="instagram",
        ig_user_id=ig_user_id,
        access_token_encrypted=encrypt_key(access_token),
        token_last4=mask_key(access_token),
        expires_at=expires_at,
        created_by=None,
    )
    repos.social_pending_state_clear(row)
    await db.flush()
    return OAuthTokenResult(
        access_token=access_token,
        fb_user_id="",
        ig_user_id=ig_user_id,
        expires_at=expires_at,
        missing_scopes=missing_scopes,
    )


def _parse_short_lived(payload: dict[str, Any]) -> tuple[str, str, list[str]]:
    node: dict[str, Any] = payload
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        node = data[0]
    access_token = str(node.get("access_token") or "")
    user_id = str(node.get("user_id") or payload.get("user_id") or "")
    scopes = _scope_list(node.get("permissions") or payload.get("permissions"))
    granted = payload.get("granted_scopes") or node.get("granted_scopes")
    if granted:
        scopes = _scope_list(granted)
    return access_token, user_id, scopes


def _scope_list(raw: object) -> list[str]:
    if isinstance(raw, str):
        return [s.strip() for s in raw.split(",") if s.strip()]
    if isinstance(raw, list):
        return [str(s).strip() for s in raw if str(s).strip()]
    return []


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        parsed = response.json()
    except ValueError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _graph_error_hint(payload: dict[str, Any], status_code: int) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "")
        code = error.get("code")
        if isinstance(code, int):
            return f"meta_oauth_graph_error:{code}"
        return message or f"meta_oauth_graph_error:{status_code}"
    if error_type := payload.get("error_type"):
        return str(error_type)
    if status_code == 400 and "error" in payload:
        return "meta_oauth_denied"
    return f"meta_oauth_graph_error:{status_code}"
