"""Instagram Login OAuth for org connect (ADR 0022 OAuth slice).

Authorization-code flow against ``https://www.instagram.com/oauth/authorize``.
The callback is a public route (Meta redirects there with no Authorization header), so the
org is recovered from the signed ``state`` and the browser round-trip is protected with a
double-submit CSRF cookie set at ``start`` time and verified at the callback.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets
import time
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
_RELAY_CALLBACK_PATH = "/meta/callback"
_RELAY_AUTHORIZE_PATH = "/authorize"
RELAY_FINISH_PATH = "/api/social/oauth/relay-finish"

# ADR 0033 — Meta Live mode requires these two endpoints on the app.
_DEAUTHORIZE_PATH = "/api/social/meta/deauthorize"
_DATA_DELETION_PATH = "/api/social/meta/data-deletion"
# Relay mode: the vendor app points at the Worker's fixed URLs instead.
_RELAY_DEAUTHORIZE_PATH = "/meta/deauthorize"
_RELAY_DATA_DELETION_PATH = "/meta/data-deletion"


def oauth_callback_url() -> str | None:
    """Exact URI Meta must whitelist — mode-aware (ADR 0032).

    BYO: `{web_base_url}/api/social/oauth/callback`. Relay: the fixed vendor
    URI `{relay}/meta/callback` (whitelisted once on the vendor app — shown
    read-only for disclosure, not for the admin to whitelist).
    ``None`` when the pieces needed for the active mode are missing.
    """
    from internal.instance.config import get_snapshot

    snap = get_snapshot()
    if snap.meta_oauth_mode == "relay":
        relay = (snap.meta_oauth_relay_url or "").strip().rstrip("/")
        return f"{relay}{_RELAY_CALLBACK_PATH}" if relay else None
    base = (snap.web_base_url or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}{_CALLBACK_PATH}"


def meta_platform_callback_urls() -> dict[str, str | None]:
    """The two dashboard URLs Meta requires before an app can go Live (ADR 0033).

    BYO: derived from ``web_base_url`` — the admin whitelists these exact
    strings under Instagram → API setup. Relay: the Worker's fixed URLs,
    whitelisted once on the vendor app (disclosure only, like the callback).
    """
    from internal.instance.config import get_snapshot

    snap = get_snapshot()
    if snap.meta_oauth_mode == "relay":
        relay = (snap.meta_oauth_relay_url or "").strip().rstrip("/")
        return {
            "deauthorize_url": f"{relay}{_RELAY_DEAUTHORIZE_PATH}" if relay else None,
            "data_deletion_url": f"{relay}{_RELAY_DATA_DELETION_PATH}" if relay else None,
        }
    base = (snap.web_base_url or "").strip().rstrip("/")
    return {
        "deauthorize_url": f"{base}{_DEAUTHORIZE_PATH}" if base else None,
        "data_deletion_url": f"{base}{_DATA_DELETION_PATH}" if base else None,
    }


def oauth_configured() -> bool:
    """True when the active mode has everything OAuth start needs."""
    from internal.instance.config import get_snapshot

    snap = get_snapshot()
    base = (snap.web_base_url or "").strip()
    if snap.meta_oauth_mode == "relay":
        # ADR 0034 — the registration secret is required too; without it the
        # ticket redeem cannot authenticate, so Connect stays guided.
        return bool(
            base
            and snap.meta_oauth_relay_url
            and snap.meta_oauth_instance_id
            and snap.meta_oauth_relay_secret
        )
    return bool(snap.meta_app_id and snap.meta_app_secret and base)


def _oauth_redirect_uri() -> str:
    uri = oauth_callback_url()
    if not uri:
        raise MetaOAuthError("meta_oauth_not_configured")
    return uri


def _oauth_fields(redirect_uri: str | None = None) -> dict[str, str]:
    from internal.instance.config import get_snapshot

    snap = get_snapshot()
    if snap.meta_oauth_mode == "relay":
        # Relay holds the vendor app creds — the instance needs the relay
        # base, its registered instance_id for the state prefix, and the
        # registration secret for the ticket redeem (ADR 0034).
        if (
            not snap.meta_oauth_relay_url
            or not snap.meta_oauth_instance_id
            or not snap.meta_oauth_relay_secret
        ):
            raise MetaOAuthError("meta_oauth_not_configured")
        return {
            "client_id": "",
            "client_secret": "",
            "redirect_uri": redirect_uri or _oauth_redirect_uri(),
        }
    if not snap.meta_app_id or not snap.meta_app_secret:
        raise MetaOAuthError("meta_oauth_not_configured")
    return {
        "client_id": snap.meta_app_id,
        "client_secret": snap.meta_app_secret,
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


def _state_value(row_id: str, token: str, instance_id: str = "") -> str:
    # Relay mode prefixes the registry slug so the worker can fan the browser
    # out to the right install: `{instance_id}:{row_id}:{blob}`.
    if instance_id:
        return f"{instance_id}:{row_id}:{token}"
    return f"{row_id}:{token}"


def parse_state(state: str) -> tuple[str, str] | None:
    """Return (row_id, encrypted blob) when the state value looks like ours.

    Relay states carry an `{instance_id}:` prefix; ``parse_relay_state``
    strips it after verifying the slug.
    """
    try:
        row_id, token = state.split(":", 1)
    except ValueError:
        return None
    if not row_id or not token:
        return None
    return row_id, token


def parse_relay_state(state: str) -> tuple[str, str] | None:
    """Strip and verify the `{instance_id}:` relay prefix, then parse."""
    from internal.instance.config import get_snapshot

    instance_id, _, rest = state.partition(":")
    if not instance_id or instance_id != get_snapshot().meta_oauth_instance_id:
        return None
    return parse_state(rest)


async def start_oauth(db: AsyncSession, *, company_id: uuid.UUID) -> OAuthStart:
    """Create the dialog URL + persist the encrypted pending state + CSRF token.

    Caller owns the transaction (commit on success, rollback on failure).
    """
    from internal.instance.config import get_snapshot

    snap = get_snapshot()
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
    if snap.meta_oauth_mode == "relay":
        # The browser goes to the relay, which 302s to Instagram with the
        # vendor app creds — the instance never sees the vendor client_id.
        relay = snap.meta_oauth_relay_url.rstrip("/")
        state = _state_value(str(row.id), blob, snap.meta_oauth_instance_id)
        return OAuthStart(
            authorization_url=f"{relay}{_RELAY_AUTHORIZE_PATH}?{urlencode({'state': state})}",
            connect_state=blob,
            csrf_token=csrf_token,
        )
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


async def _validated_pending_row(
    db: AsyncSession,
    row_id_str: str,
    csrf_token: str | None,
) -> tuple[SocialAccount, dict[str, str]]:
    """Shared pending-state gate for both finish paths: row exists, encrypted
    blob decrypts, row_id matches, and the double-submit CSRF cookie value
    matches the token embedded at start time."""
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
    if str(payload.get("row_id") or "") != row_id_str:
        raise MetaOAuthError("meta_oauth_invalid_state")
    stored_csrf = str(payload.get("csrf_token") or "")
    if not stored_csrf or stored_csrf != (csrf_token or ""):
        raise MetaOAuthError("meta_oauth_csrf_mismatch")
    return row, payload


async def _persist_token_result(
    db: AsyncSession,
    row: SocialAccount,
    *,
    access_token: str,
    ig_user_id: str,
    expires_at: datetime | None,
    missing_scopes: list[str],
) -> OAuthTokenResult:
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
    from internal.instance.config import get_snapshot

    if get_snapshot().meta_oauth_mode == "relay":
        # In relay mode Meta never calls this instance — the relay exchanged
        # the code; the browser lands on /oauth/relay-finish instead.
        raise MetaOAuthError("meta_oauth_mode_unavailable")
    parsed = parse_state(state)
    if parsed is None:
        raise MetaOAuthError("meta_oauth_invalid_state")
    row, payload = await _validated_pending_row(db, parsed[0], csrf_token)

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

    return await _persist_token_result(
        db,
        row,
        access_token=access_token,
        ig_user_id=ig_user_id,
        expires_at=expires_at,
        missing_scopes=missing_scopes,
    )


async def redeem_relay_ticket(
    db: AsyncSession,
    *,
    ticket: str,
    state: str,
    csrf_token: str | None,
) -> OAuthTokenResult:
    """Relay-mode finish (ADR 0032 §3): the vendor relay exchanged the code
    already; the browser lands here with a one-time ticket. We re-validate the
    pending state + CSRF cookie exactly like the BYO callback, redeem the
    ticket server-to-server with the shared-secret proof (ADR 0034 — read-once,
    60s TTL on the relay), verify the payload is bound to this install, then
    persist the token.

    Caller owns the transaction (commit on success, rollback on failure).
    """
    from internal.instance.config import get_snapshot

    snap = get_snapshot()
    if snap.meta_oauth_mode != "relay":
        raise MetaOAuthError("meta_oauth_mode_unavailable")
    if not snap.meta_oauth_relay_secret:
        # ADR 0034 — no shared secret, no way to prove ourselves to the relay.
        raise MetaOAuthError("meta_oauth_not_configured")
    parsed = parse_relay_state(state)
    if parsed is None:
        raise MetaOAuthError("meta_oauth_invalid_state")
    row, _ = await _validated_pending_row(db, parsed[0], csrf_token)

    relay = snap.meta_oauth_relay_url.rstrip("/")
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{relay}/ticket/{ticket}",
            params={
                "sig": relay_ticket_signature(snap.meta_oauth_relay_secret, ticket)
            },
        )
    if resp.status_code == 404:
        raise MetaOAuthError("meta_oauth_relay_ticket_expired")
    if not resp.is_success:
        raise MetaOAuthError("meta_oauth_exchange_failed")
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if str(payload.get("instance_id") or "") != snap.meta_oauth_instance_id:
        # Ticket redeemed against a payload bound to a different install.
        raise MetaOAuthError("meta_oauth_invalid_state")
    access_token = str(payload.get("access_token") or "")
    ig_user_id = str(payload.get("ig_user_id") or "")
    if not access_token or not ig_user_id:
        raise MetaOAuthError("meta_oauth_exchange_failed")
    expires_at: datetime | None = None
    raw_expires = str(payload.get("expires_at") or "")
    if raw_expires:
        try:
            expires_at = datetime.fromisoformat(raw_expires)
        except ValueError:
            expires_at = None
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
    raw_missing = payload.get("missing_scopes")
    missing_scopes = (
        [str(s) for s in raw_missing] if isinstance(raw_missing, list) else []
    )

    return await _persist_token_result(
        db,
        row,
        access_token=access_token,
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


# --- Meta platform callbacks (ADR 0033) — Live mode requirements ---


def _b64url_decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def parse_signed_request(raw: str, secret: str) -> dict[str, Any] | None:
    """Verify a Meta ``signed_request`` (``<b64url sig>.<b64url json>``).

    The signature is HMAC-SHA256 over the payload segment keyed by the app
    secret — it is the only auth these unauthenticated endpoints get.
    """
    if not raw or not secret:
        return None
    sig_b64, sep, payload_b64 = raw.partition(".")
    if not sep or not sig_b64 or not payload_b64:
        return None
    try:
        sig = _b64url_decode(sig_b64)
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, binascii.Error):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("algorithm") or "").upper() != "HMAC-SHA256":
        return None
    # Meta signs the base64url-encoded payload text, not the decoded bytes.
    expected = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    return payload


async def _disconnect_ig_user(db: AsyncSession, ig_user_id: str) -> int:
    deleted = await repos.delete_social_accounts_by_ig_user_id(db, ig_user_id)
    if deleted:
        logger.info(
            "meta platform callback disconnected ig_user_id=%s rows=%d",
            ig_user_id,
            deleted,
        )
    return deleted


def _signed_request_ig_user_id(raw: str, secret: str) -> str:
    payload = parse_signed_request(raw, secret)
    if payload is None:
        raise MetaOAuthError("meta_oauth_invalid_signed_request")
    return str(payload.get("user_id") or "").strip()


def _data_deletion_code(ig_user_id: str) -> str:
    """Stateless confirmation code — HMAC-signed under JWT_SECRET (ADR 0033 §1)."""
    body = (
        base64.urlsafe_b64encode(
            json.dumps(
                {"u": ig_user_id, "t": int(time.time())}, separators=(",", ":")
            ).encode()
        )
        .decode()
        .rstrip("=")
    )
    sig = hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_data_deletion_code(code: str) -> str | None:
    """Return the ig_user_id when the status code is one we issued."""
    body, sep, sig = code.partition(".")
    if not sep:
        return None
    expected = hmac.new(
        settings.jwt_secret.encode(), body.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
    except (ValueError, binascii.Error):
        return None
    if not isinstance(payload, dict):
        return None
    return str(payload.get("u") or "") or None


def _data_deletion_status_url(code: str) -> str:
    from internal.instance.config import get_snapshot

    base = (get_snapshot().web_base_url or "").strip().rstrip("/")
    return f"{base}{_DATA_DELETION_PATH}/{code}"


async def process_deauthorize(db: AsyncSession, *, signed_request: str) -> str:
    """Meta deauthorize callback: the user removed the app — drop every stored
    connection for that IG user. Returns the ig_user_id ("" when the payload
    carries none — still a valid, signed ping). Caller owns the transaction."""
    from internal.instance.config import get_snapshot

    snap = get_snapshot()
    if snap.meta_oauth_mode == "relay":
        # Meta only ever calls the vendor app; the relay forwards these via
        # process_relay_platform_event instead.
        raise MetaOAuthError("meta_oauth_mode_unavailable")
    ig_user_id = _signed_request_ig_user_id(signed_request, snap.meta_app_secret)
    if ig_user_id:
        await _disconnect_ig_user(db, ig_user_id)
    return ig_user_id


async def process_data_deletion(
    db: AsyncSession, *, signed_request: str
) -> tuple[str, str]:
    """Meta data-deletion callback — returns ``(confirmation_code, status_url)``.

    Deletion is synchronous (the social_accounts row is all we hold keyed to
    the IG user), so the status URL always reports ``completed``. Caller owns
    the transaction.
    """
    from internal.instance.config import get_snapshot

    snap = get_snapshot()
    if snap.meta_oauth_mode == "relay":
        raise MetaOAuthError("meta_oauth_mode_unavailable")
    ig_user_id = _signed_request_ig_user_id(signed_request, snap.meta_app_secret)
    if ig_user_id:
        await _disconnect_ig_user(db, ig_user_id)
    code = _data_deletion_code(ig_user_id)
    return code, _data_deletion_status_url(code)


RELAY_EVENT_KINDS = frozenset({"deauthorize", "data_deletion"})


def relay_event_signature(kind: str, ig_user_id: str, secret: str) -> str:
    """Shared-secret signature the relay puts on forwarded platform events
    (ADR 0033 §3, key updated by ADR 0034): HMAC-SHA256 keyed by this
    install's registration secret — the public registry slug proves nothing."""
    return hmac.new(
        secret.encode(), f"{kind}:{ig_user_id}".encode(), hashlib.sha256
    ).hexdigest()


def relay_ticket_signature(secret: str, ticket: str) -> str:
    """ADR 0034 §2 — the redeem-side proof the Worker checks on
    ``GET /ticket/{id}``: HMAC-SHA256 keyed by the install's shared secret
    over a domain-separated message."""
    return hmac.new(
        secret.encode(), f"ticket:{ticket}".encode(), hashlib.sha256
    ).hexdigest()


async def process_relay_platform_event(
    db: AsyncSession, *, kind: str, ig_user_id: str, sig: str
) -> dict[str, Any]:
    """Relay-forwarded deauthorize / data-deletion (ADR 0033 §3).

    In relay mode the instance has no app secret, so the vendor relay verifies
    Meta's ``signed_request`` and re-signs the event with this install's
    registry slug. Caller owns the transaction.
    """
    from internal.instance.config import get_snapshot

    snap = get_snapshot()
    if snap.meta_oauth_mode != "relay":
        raise MetaOAuthError("meta_oauth_mode_unavailable")
    secret = snap.meta_oauth_relay_secret
    expected = relay_event_signature(kind, ig_user_id, secret)
    if (
        kind not in RELAY_EVENT_KINDS
        or not ig_user_id
        or not secret
        or not hmac.compare_digest(sig or "", expected)
    ):
        raise MetaOAuthError("meta_oauth_invalid_signed_request")
    await _disconnect_ig_user(db, ig_user_id)
    if kind == "deauthorize":
        return {"ok": True}
    code = _data_deletion_code(ig_user_id)
    return {"url": _data_deletion_status_url(code), "confirmation_code": code}
