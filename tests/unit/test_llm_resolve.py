"""Per-turn LLM resolver — env fallback vs org bundle (no live network)."""

from __future__ import annotations

import pytest

from internal.llm.resolve import (
    CompanyLlmBundle,
    FailedOrgSlot,
    ResolvedModel,
    bundle_has_credentials,
    env_has_llm_credentials,
    llm_bundle_scope,
    prefix_litellm_model,
    resolve_image,
    resolve_llm_model,
)
from internal.llm.router import LlmProviderError, ModelTier, has_llm_credentials


def _org(
    model_id: str,
    *,
    api_key: str = "sk-org",
    api_base: str | None = "https://openrouter.ai/api/v1",
    provider_type: str = "openai_compatible",
) -> ResolvedModel:
    return ResolvedModel(
        model_id=model_id,
        api_key=api_key,
        api_base=api_base,
        provider_type=provider_type,  # type: ignore[arg-type]
        source="org",
        key_last4="org1",
    )


def test_unbound_uses_env_models(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "llm_cheap_model", "gpt-4o-mini")
    monkeypatch.setattr(config.settings, "llm_strong_model", "gpt-4o")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-env")
    monkeypatch.setattr(config.settings, "anthropic_api_key", None)
    monkeypatch.setattr(config.settings, "llm_api_base", None)
    resolved = resolve_llm_model(ModelTier.CHEAP)
    assert resolved.source == "env"
    assert resolved.model_id == "gpt-4o-mini"
    assert resolved.api_key == "sk-env"
    assert resolved.provider_type == "openai"
    assert resolve_llm_model(ModelTier.STRONG).model_id == "gpt-4o"


def test_env_api_base_marks_openai_compatible(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "llm_cheap_model", "deepseek-chat")
    monkeypatch.setattr(config.settings, "llm_api_base", "https://api.deepseek.com")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-ds")
    monkeypatch.setattr(config.settings, "anthropic_api_key", None)
    resolved = resolve_llm_model(ModelTier.CHEAP)
    assert resolved.provider_type == "openai_compatible"
    assert resolved.api_base == "https://api.deepseek.com"
    assert prefix_litellm_model(resolved.model_id, resolved.api_base) == "openai/deepseek-chat"


def test_per_slot_org_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "llm_cheap_model", "gpt-4o-mini")
    monkeypatch.setattr(config.settings, "llm_strong_model", "gpt-4o")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-env")
    monkeypatch.setattr(config.settings, "llm_api_base", None)
    bundle = CompanyLlmBundle(strong=_org("fable-5"))
    with llm_bundle_scope(bundle):
        cheap = resolve_llm_model(ModelTier.CHEAP)
        strong = resolve_llm_model(ModelTier.STRONG)
    assert cheap.source == "env"
    assert cheap.model_id == "gpt-4o-mini"
    assert strong.source == "org"
    assert strong.model_id == "fable-5"
    assert strong.api_key == "sk-org"


def test_org_api_base_prefixes_bare_id() -> None:
    resolved = _org("deepseek-v4-flash")
    assert prefix_litellm_model(resolved.model_id, resolved.api_base) == (
        "openai/deepseek-v4-flash"
    )
    already = _org("openai/foo")
    assert prefix_litellm_model(already.model_id, already.api_base) == "openai/foo"


def test_decrypt_failure_raises_auth_not_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "llm_strong_model", "gpt-4o")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-env")
    bundle = CompanyLlmBundle(strong=FailedOrgSlot(model_id="fable-5"))
    with llm_bundle_scope(bundle), pytest.raises(LlmProviderError) as ei:
        resolve_llm_model(ModelTier.STRONG)
    assert ei.value.kind == "auth"
    assert "fable-5" in (ei.value.model or "")


def test_has_llm_credentials_org_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "openai_api_key", None)
    monkeypatch.setattr(config.settings, "anthropic_api_key", None)
    assert not env_has_llm_credentials()
    assert not has_llm_credentials()
    with llm_bundle_scope(CompanyLlmBundle(cheap=_org("deepseek-v4-flash"))):
        assert bundle_has_credentials()
        assert has_llm_credentials()
    assert not has_llm_credentials()


def test_unbound_empty_env_has_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "openai_api_key", "")
    monkeypatch.setattr(config.settings, "anthropic_api_key", None)
    assert not has_llm_credentials()


def test_resolve_image_env_and_org(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "llm_image_model", "dall-e-3")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-env")
    monkeypatch.setattr(config.settings, "llm_api_base", None)
    env_img = resolve_image()
    assert env_img is not None
    assert env_img.model_id == "dall-e-3"
    assert env_img.source == "env"
    with llm_bundle_scope(CompanyLlmBundle(image=_org("seedream-4.5"))):
        org_img = resolve_image()
    assert org_img is not None
    assert org_img.source == "org"
    assert org_img.model_id == "seedream-4.5"


def test_resolve_image_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "llm_image_model", "")
    assert resolve_image() is None
