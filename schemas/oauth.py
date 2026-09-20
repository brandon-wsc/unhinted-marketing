"""Meta OAuth connect flow API shapes (social_accounts OAuth slice).

The browser never sees raw tokens; the backend exchanges the auth code and
encrypts the resulting access token under BYOK_ENCRYPTION_KEY. Only the
connection state is serialized.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class OAuthStatus(StrEnum):
    not_connected = "not_connected"
    connected = "connected"
    pending = "pending"
    failed = "failed"


class SocialOAuthInfo(BaseModel):
    """Current connection state for an org's Instagram account."""

    status: OAuthStatus = OAuthStatus.not_connected
    # Short-lived authorization URL — open in a popup / new tab to start the flow.
    authorization_url: str | None = None
    # Present when connecting (fetch this URL to poll the result).
    poll_url: str | None = None
    # ADR 0032 — whether the instance Meta app creds + callback base are set;
    # False renders the guided BYO setup card instead of a failing Connect.
    configured: bool = False
    # Exact string to whitelist under Meta Valid OAuth Redirect URIs (BYO);
    # in relay mode this is the vendor relay's fixed URI (disclosure only).
    callback_url: str | None = None
    # ADR 0032 §3 — which path connect uses; the UI discloses relay transit.
    mode: Literal["byo", "relay"] = "byo"
    # ADR 0033 — dashboard URLs Meta requires before the app can go Live
    # (BYO: derived from web_base_url; relay: the vendor's fixed URLs).
    deauthorize_url: str | None = None
    data_deletion_url: str | None = None


class MetaDataDeletionResponse(BaseModel):
    """Meta data-deletion callback answer — Meta shows the user url + code."""

    url: str
    confirmation_code: str


class MetaDataDeletionStatus(BaseModel):
    """Status lookup behind the confirmation code (deletion is synchronous)."""

    confirmation_code: str
    status: Literal["completed"] = "completed"


class MetaRelayEvent(BaseModel):
    """Relay-forwarded platform event (ADR 0033 §3). ``sig`` is HMAC-SHA256
    over ``{kind}:{ig_user_id}`` keyed by this install's registry slug."""

    kind: Literal["deauthorize", "data_deletion"]
    ig_user_id: str = Field(min_length=1, max_length=64)
    sig: str = Field(min_length=1, max_length=128)


class MetaRelayResult(BaseModel):
    ok: bool = True
    url: str | None = None
    confirmation_code: str | None = None
