"""Org BYOK HTTP API (ADR 0020) — editor-only; probes mocked (no live key)."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.byok import ByokModelListProxy, ByokProbeResult
from tests.api.helpers import auth_header, join_org, register_user

SECRET_KEY = "sk-live-super-secret-value"


def _base(company_id: str) -> str:
    return f"/api/companies/{company_id}/byok"


async def _owner(client: AsyncClient) -> tuple[dict[str, str], str]:
    data = await register_user(client)
    company_id = data["user"]["organizations"][0]["id"]
    return auth_header(data["access_token"]), company_id


def _assert_no_secret(payload: Any) -> None:
    dumped = str(payload)
    assert SECRET_KEY not in dumped
    assert "api_key_encrypted" not in dumped


@pytest.fixture
def skip_background_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cmd.api.routes.byok.run_provider_auth_probe",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "cmd.api.routes.byok.run_model_format_probe",
        AsyncMock(return_value=None),
    )


@pytest.mark.asyncio
async def test_byok_unauthenticated(client: AsyncClient) -> None:
    res = await client.get(f"/api/companies/{uuid.uuid4()}/byok/providers")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_byok_member_forbidden(
    client: AsyncClient, db_session: AsyncSession, skip_background_probes: None
) -> None:
    owner = await register_user(client, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
    company_id = owner["user"]["organizations"][0]["id"]
    member = await register_user(client, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
    await join_org(
        db_session,
        user_id=uuid.UUID(member["user"]["id"]),
        company_id=uuid.UUID(company_id),
        role="member",
    )
    res = await client.get(
        f"{_base(company_id)}/providers",
        headers=auth_header(member["access_token"]),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_provider_crud_never_leaks_key(
    client: AsyncClient, skip_background_probes: None
) -> None:
    headers, company_id = await _owner(client)
    create = await client.post(
        f"{_base(company_id)}/providers",
        headers=headers,
        json={
            "label": "OpenRouter main",
            "provider_type": "openai_compatible",
            "api_key": SECRET_KEY,
            "api_base": "https://openrouter.ai/api/v1",
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    _assert_no_secret(body)
    assert body["key_last4"] == SECRET_KEY[-4:]
    assert body["label"] == "OpenRouter main"
    assert body["verified"] is False
    pid = body["id"]

    listed = await client.get(f"{_base(company_id)}/providers", headers=headers)
    assert listed.status_code == 200
    _assert_no_secret(listed.json())
    assert listed.json()["items"][0]["id"] == pid

    patched = await client.patch(
        f"{_base(company_id)}/providers/{pid}",
        headers=headers,
        json={"label": "OpenRouter rotated", "api_key": ""},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["label"] == "OpenRouter rotated"
    assert patched.json()["key_last4"] == SECRET_KEY[-4:]
    _assert_no_secret(patched.json())


@pytest.mark.asyncio
async def test_private_api_base_rejected(
    client: AsyncClient, skip_background_probes: None
) -> None:
    headers, company_id = await _owner(client)
    res = await client.post(
        f"{_base(company_id)}/providers",
        headers=headers,
        json={
            "label": "local",
            "provider_type": "openai_compatible",
            "api_key": SECRET_KEY,
            "api_base": "http://127.0.0.1:8080/v1",
        },
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_two_phase_provider_and_model_delete(
    client: AsyncClient, skip_background_probes: None
) -> None:
    headers, company_id = await _owner(client)
    provider = (
        await client.post(
            f"{_base(company_id)}/providers",
            headers=headers,
            json={
                "label": "OpenAI",
                "provider_type": "openai",
                "api_key": SECRET_KEY,
            },
        )
    ).json()
    pid = provider["id"]
    model = (
        await client.post(
            f"{_base(company_id)}/models",
            headers=headers,
            json={
                "provider_id": pid,
                "model_id": "gpt-4o-mini",
                "capability": "chat",
                "capability_source": "manual",
            },
        )
    ).json()
    mid = model["id"]
    routed = await client.put(
        f"{_base(company_id)}/routing",
        headers=headers,
        json={"cheap_model_id": mid, "medium_model_id": None, "strong_model_id": None, "image_model_id": None},
    )
    assert routed.status_code == 200, routed.text

    blocked_model = await client.delete(f"{_base(company_id)}/models/{mid}", headers=headers)
    assert blocked_model.status_code == 409
    assert blocked_model.json()["detail"]["code"] == "has_dependents"
    assert "cheap" in blocked_model.json()["detail"]["slots"]

    forced_model = await client.delete(
        f"{_base(company_id)}/models/{mid}?force=true", headers=headers
    )
    assert forced_model.status_code == 200
    assert forced_model.json()["cleared_slots"] == ["cheap"]

    model2 = (
        await client.post(
            f"{_base(company_id)}/models",
            headers=headers,
            json={
                "provider_id": pid,
                "model_id": "gpt-4o",
                "capability": "chat",
                "capability_source": "manual",
            },
        )
    ).json()
    blocked_provider = await client.delete(
        f"{_base(company_id)}/providers/{pid}", headers=headers
    )
    assert blocked_provider.status_code == 409
    assert blocked_provider.json()["detail"]["models"][0]["id"] == model2["id"]

    forced_provider = await client.delete(
        f"{_base(company_id)}/providers/{pid}?force=true", headers=headers
    )
    assert forced_provider.status_code == 200
    assert model2["id"] in forced_provider.json()["removed_models"]


@pytest.mark.asyncio
async def test_post_models_attaches_existing(
    client: AsyncClient, skip_background_probes: None
) -> None:
    headers, company_id = await _owner(client)
    pid = (
        await client.post(
            f"{_base(company_id)}/providers",
            headers=headers,
            json={"label": "k", "provider_type": "openai", "api_key": SECRET_KEY},
        )
    ).json()["id"]
    first = await client.post(
        f"{_base(company_id)}/models",
        headers=headers,
        json={
            "provider_id": pid,
            "model_id": "gpt-4o-mini",
            "capability": "chat",
            "capability_source": "inferred",
        },
    )
    assert first.status_code == 201, first.text
    mid = first.json()["id"]
    again = await client.post(
        f"{_base(company_id)}/models",
        headers=headers,
        json={
            "provider_id": pid,
            "model_id": "gpt-4o-mini",
            "capability": "image",
            "capability_source": "manual",
        },
    )
    assert again.status_code == 200, again.text
    assert again.json()["id"] == mid
    assert again.json()["capability"] == "image"
    listed = await client.get(f"{_base(company_id)}/models", headers=headers)
    assert len(listed.json()["items"]) == 1


@pytest.mark.asyncio
async def test_routing_capability_and_env_fallback(
    client: AsyncClient, skip_background_probes: None
) -> None:
    headers, company_id = await _owner(client)
    pid = (
        await client.post(
            f"{_base(company_id)}/providers",
            headers=headers,
            json={"label": "k", "provider_type": "openai", "api_key": SECRET_KEY},
        )
    ).json()["id"]
    image = (
        await client.post(
            f"{_base(company_id)}/models",
            headers=headers,
            json={
                "provider_id": pid,
                "model_id": "dall-e-3",
                "capability": "image",
                "capability_source": "manual",
            },
        )
    ).json()
    chat = (
        await client.post(
            f"{_base(company_id)}/models",
            headers=headers,
            json={
                "provider_id": pid,
                "model_id": "gpt-4o",
                "capability": "chat",
                "capability_source": "manual",
            },
        )
    ).json()
    mismatch = await client.put(
        f"{_base(company_id)}/routing",
        headers=headers,
        json={
            "cheap_model_id": image["id"],
            "medium_model_id": None,
            "strong_model_id": None,
            "image_model_id": None,
        },
    )
    assert mismatch.status_code == 422

    ok = await client.put(
        f"{_base(company_id)}/routing",
        headers=headers,
        json={
            "cheap_model_id": None,
            "medium_model_id": None,
            "strong_model_id": chat["id"],
            "image_model_id": image["id"],
        },
    )
    assert ok.status_code == 200, ok.text
    by_slot = {s["slot"]: s for s in ok.json()["slots"]}
    assert by_slot["strong"]["source"] == "org"
    assert by_slot["strong"]["model_id"] == "gpt-4o"
    assert by_slot["cheap"]["source"] == "env"
    assert by_slot["image"]["source"] == "org"


@pytest.mark.asyncio
async def test_provider_test_and_model_list_mocked(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, skip_background_probes: None
) -> None:
    monkeypatch.setattr(
        "cmd.api.routes.byok.probe_provider_auth",
        AsyncMock(return_value=ByokProbeResult(ok=True)),
    )
    monkeypatch.setattr(
        "cmd.api.routes.byok.cached_provider_models",
        AsyncMock(
            return_value=ByokModelListProxy(
                fetchable=True,
                models=[{"id": "gpt-4o", "capability": "chat", "capability_source": "inferred"}],
            )
        ),
    )
    headers, company_id = await _owner(client)
    pid = (
        await client.post(
            f"{_base(company_id)}/providers",
            headers=headers,
            json={"label": "k", "provider_type": "openai", "api_key": SECRET_KEY},
        )
    ).json()["id"]
    tested = await client.post(f"{_base(company_id)}/providers/{pid}/test", headers=headers)
    assert tested.status_code == 200, tested.text
    assert tested.json()["ok"] is True
    catalog = await client.get(f"{_base(company_id)}/providers/{pid}/models", headers=headers)
    assert catalog.status_code == 200
    assert catalog.json()["fetchable"] is True
    assert catalog.json()["models"][0]["id"] == "gpt-4o"


@pytest.mark.asyncio
async def test_image_test_requires_confirm_paid(
    client: AsyncClient, skip_background_probes: None
) -> None:
    headers, company_id = await _owner(client)
    pid = (
        await client.post(
            f"{_base(company_id)}/providers",
            headers=headers,
            json={"label": "k", "provider_type": "openai", "api_key": SECRET_KEY},
        )
    ).json()["id"]
    mid = (
        await client.post(
            f"{_base(company_id)}/models",
            headers=headers,
            json={
                "provider_id": pid,
                "model_id": "dall-e-3",
                "capability": "image",
                "capability_source": "manual",
            },
        )
    ).json()["id"]
    denied = await client.post(f"{_base(company_id)}/models/{mid}/test", headers=headers)
    assert denied.status_code == 400
