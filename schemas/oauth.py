"""Meta OAuth connect flow API shapes (social_accounts OAuth slice).

The browser never sees raw tokens; the backend exchanges the auth code and
encrypts the resulting access token under BYOK_ENCRYPTION_KEY. Only the
connection state is serialized.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


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


class SocialOAuthPoll(BaseModel):
    status: OAuthStatus
    # OAuth pending state names (facebook | instagram_basic | instagram_content_publish |
    # pages_show_list | unknown | access_denied).
    missing_scope: str | None = None
    message: str | None = None
