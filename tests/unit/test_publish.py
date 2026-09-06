"""Publish adapter (ADR 0022) — stub + mocked Instagram Graph; no live Meta."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet

from internal.llm.keys import encrypt_key
from internal.memory.models import SocialAccount
from internal.tools.publish import (
    ERROR_PERMISSION,
    ERROR_PLATFORM,
    ERROR_TOKEN_EXPIRED,
    FAILED_STATUS,
    PUBLISHED_STATUS,
    STUB_STATUS,
    PublishPreconditionError,
    classify_graph_error,
    compose_caption,
    publish_social_post,
)
from schemas.contracts import DraftCopy
from schemas.tools import PublishSocialPostRequest

IG_USER = "17841400000000"
TOKEN = "IGQW-long-lived-access-token"
IMAGE = "https://cdn.example/post.png"


def _req(**overrides: object) -> PublishSocialPostRequest:
    payload: dict = {
        "session_id": uuid.uuid4(),
        "approval_token": "token-ok-12",
        "idempotency_key": "idem-key-12",
        "draft_copy": DraftCopy(caption="今日奶茶", hashtags=["hkfood"], cta="嚟啦"),
        "image_url": IMAGE,
        "revision": 1,
        "platform": "instagram",
    }
    payload.update(overrides)
    return PublishSocialPostRequest.model_validate(payload)


def _account(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> SocialAccount:
    from internal import config

    kek = Fernet.generate_key().decode()
    monkeypatch.setattr(config.settings, "byok_encryption_key", kek)
    monkeypatch.setattr(config.settings, "publish_adapter", "instagram")
    monkeypatch.setattr(config.settings, "meta_graph_api_version", "v22.0")
    fields: dict = {
        "company_id": uuid.uuid4(),
        "platform": "instagram",
        "ig_user_id": IG_USER,
        "access_token_encrypted": encrypt_key(TOKEN),
        "token_last4": TOKEN[-4:],
        "expires_at": None,
    }
    fields.update(overrides)
    return SocialAccount(**fields)


def _patch_account(monkeypatch: pytest.MonkeyPatch, account: SocialAccount | None) -> None:
    monkeypatch.setattr(
        "internal.tools.publish.repos.get_social_account",
        AsyncMock(return_value=account),
    )


class ScriptedClient:
    def __init__(
        self,
        posts: list[tuple[int, dict] | BaseException],
        gets: list[tuple[int, dict]] | None = None,
    ) -> None:
        self._posts = list(posts)
        self._gets = list(gets or [])
        self.post_urls: list[str] = []
        self.get_urls: list[str] = []

    async def __aenter__(self) -> ScriptedClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, data: dict | None = None) -> httpx.Response:
        self.post_urls.append(url)
        item = self._posts.pop(0)
        if isinstance(item, BaseException):
            raise item
        status, body = item
        return httpx.Response(status, json=body)

    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        self.get_urls.append(url)
        status, body = self._gets.pop(0)
        return httpx.Response(status, json=body)


def test_compose_caption_joins_copy_blocks() -> None:
    copy = DraftCopy(caption="  今日奶茶  ", hashtags=["hkfood", "#tea"], cta="嚟啦")
    assert compose_caption(copy) == "今日奶茶\n\n#hkfood #tea\n\n嚟啦"


def test_compose_caption_skips_empty_parts() -> None:
    assert compose_caption(DraftCopy(caption="", hashtags=[], cta="")) == ""
    assert compose_caption(DraftCopy(caption="only")) == "only"


def test_classify_graph_error_kinds() -> None:
    assert (
        classify_graph_error({"error": {"code": 190, "type": "OAuthException"}}, 400)
        == ERROR_TOKEN_EXPIRED
    )
    assert classify_graph_error({"error": {"code": 10}}, 400) == ERROR_PERMISSION
    assert classify_graph_error({"error": {"code": 1}}, 500) == ERROR_PLATFORM
    assert classify_graph_error({}, 403) == ERROR_PERMISSION


@pytest.mark.asyncio
async def test_stub_adapter_does_not_call_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "publish_adapter", "stub")
    called = False

    def _boom(*args: object, **kwargs: object) -> ScriptedClient:
        nonlocal called
        called = True
        raise AssertionError("stub must not open httpx")

    monkeypatch.setattr("internal.tools.publish.httpx.AsyncClient", _boom)
    outcome = await publish_social_post(AsyncMock(), _req(), company_id=uuid.uuid4())
    assert outcome.status == STUB_STATUS
    assert outcome.platform == "stub"
    assert not called


@pytest.mark.asyncio
async def test_instagram_two_phase_success(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account(monkeypatch)
    _patch_account(monkeypatch, account)
    client = ScriptedClient(
        posts=[
            (200, {"id": "container-1"}),
            (200, {"id": "media-99"}),
        ],
        gets=[(200, {"permalink": "https://www.instagram.com/p/ABC/"})],
    )
    monkeypatch.setattr(
        "internal.tools.publish.httpx.AsyncClient",
        lambda *a, **k: client,
    )
    outcome = await publish_social_post(AsyncMock(), _req(), company_id=account.company_id)
    assert outcome.status == PUBLISHED_STATUS
    assert outcome.platform == "instagram"
    assert outcome.permalink == "https://www.instagram.com/p/ABC/"
    assert outcome.media_id == "media-99"
    assert outcome.error_kind is None
    assert account.last_error_kind is None
    assert account.last_verified_at is not None
    assert f"https://graph.instagram.com/v22.0/{IG_USER}/media" == client.post_urls[0]
    assert f"https://graph.instagram.com/v22.0/{IG_USER}/media_publish" == client.post_urls[1]


@pytest.mark.asyncio
async def test_instagram_missing_account(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "publish_adapter", "instagram")
    _patch_account(monkeypatch, None)
    with pytest.raises(PublishPreconditionError, match="social_account_not_connected"):
        await publish_social_post(AsyncMock(), _req(), company_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_instagram_placeholder_account_not_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _account(
        monkeypatch,
        ig_user_id="",
        access_token_encrypted="",
        token_last4="",
    )
    _patch_account(monkeypatch, account)
    monkeypatch.setattr(
        "internal.tools.publish.httpx.AsyncClient",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("placeholder account must not call Graph")
        ),
    )
    with pytest.raises(PublishPreconditionError, match="social_account_not_connected"):
        await publish_social_post(AsyncMock(), _req(), company_id=account.company_id)


@pytest.mark.asyncio
async def test_instagram_expired_token_skips_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account(
        monkeypatch,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    _patch_account(monkeypatch, account)
    monkeypatch.setattr(
        "internal.tools.publish.httpx.AsyncClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("expired token must not call Graph")),
    )
    outcome = await publish_social_post(AsyncMock(), _req(), company_id=account.company_id)
    assert outcome.status == FAILED_STATUS
    assert outcome.error_kind == ERROR_TOKEN_EXPIRED
    assert account.last_error_kind == ERROR_TOKEN_EXPIRED


@pytest.mark.asyncio
async def test_instagram_non_http_image_is_platform_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _account(monkeypatch)
    _patch_account(monkeypatch, account)
    monkeypatch.setattr(
        "internal.tools.publish.httpx.AsyncClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("placeholder URL must not call Graph")),
    )
    outcome = await publish_social_post(
        AsyncMock(),
        _req(image_url="placeholder://seed"),
        company_id=account.company_id,
    )
    assert outcome.status == FAILED_STATUS
    assert outcome.error_kind == ERROR_PLATFORM


@pytest.mark.asyncio
async def test_instagram_permission_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account(monkeypatch)
    _patch_account(monkeypatch, account)
    client = ScriptedClient(
        posts=[
            (400, {"error": {"code": 10, "message": "Application does not have permission"}}),
        ]
    )
    monkeypatch.setattr(
        "internal.tools.publish.httpx.AsyncClient",
        lambda *a, **k: client,
    )
    outcome = await publish_social_post(AsyncMock(), _req(), company_id=account.company_id)
    assert outcome.status == FAILED_STATUS
    assert outcome.error_kind == ERROR_PERMISSION
    assert account.last_error_kind == ERROR_PERMISSION
    assert TOKEN not in (outcome.message or "")


@pytest.mark.asyncio
async def test_instagram_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account(monkeypatch)
    _patch_account(monkeypatch, account)
    client = ScriptedClient(posts=[httpx.TimeoutException("timed out")])
    monkeypatch.setattr(
        "internal.tools.publish.httpx.AsyncClient",
        lambda *a, **k: client,
    )
    outcome = await publish_social_post(AsyncMock(), _req(), company_id=account.company_id)
    assert outcome.status == FAILED_STATUS
    assert outcome.error_kind == ERROR_PLATFORM
