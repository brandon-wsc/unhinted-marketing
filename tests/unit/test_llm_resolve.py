"""Per-turn LLM resolver — env fallback vs org bundle (no live network)."""

from __future__ import annotations

import pytest

from internal.llm.resolve import (
    CompanyLlmBundle,
    FailedOrgSlot,
    ResolvedModel,
    bundle_has_credentials,
    effective_api_base,
    env_has_llm_credentials,
    gemini_catalog_id,
    gemini_litellm_model_id,
    litellm_model_id,
    llm_bundle_scope,
    openai_compat_model_id,
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


def test_openai_compat_model_id_keeps_openrouter_slug() -> None:
    assert openai_compat_model_id("deepseek/deepseek-v4-flash-0731") == (
        "deepseek/deepseek-v4-flash-0731"
    )
    assert openai_compat_model_id("openai/deepseek/deepseek-v4-flash-0731") == (
        "deepseek/deepseek-v4-flash-0731"
    )
    assert openai_compat_model_id("openrouter/bytedance-seed/seedream-4.5") == (
        "bytedance-seed/seedream-4.5"
    )
    assert openai_compat_model_id("anthropic/claude-sonnet-4") == "anthropic/claude-sonnet-4"
    assert openai_compat_model_id("gpt-4o-mini") == "gpt-4o-mini"


def test_prefix_litellm_model_keeps_slash_slug() -> None:
    base = "https://openrouter.ai/api/v1"
    assert prefix_litellm_model("deepseek/deepseek-v4-flash-0731", base) == (
        "openai/deepseek/deepseek-v4-flash-0731"
    )
    assert prefix_litellm_model("openai/deepseek/deepseek-v4-flash-0731", base) == (
        "openai/deepseek/deepseek-v4-flash-0731"
    )
    assert prefix_litellm_model("openrouter/bytedance-seed/seedream-4.5", base) == (
        "openai/bytedance-seed/seedream-4.5"
    )
    assert prefix_litellm_model("anthropic/claude-sonnet-4", base) == (
        "openai/anthropic/claude-sonnet-4"
    )
    assert prefix_litellm_model("gpt-4o-mini", base) == "openai/gpt-4o-mini"
    assert prefix_litellm_model("deepseek/deepseek-v4-flash-0731", None) == (
        "deepseek/deepseek-v4-flash-0731"
    )


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
    monkeypatch.setattr(config.settings, "gemini_api_key", None)
    monkeypatch.setattr(config.settings, "vertex_ai_api_key", None)
    monkeypatch.setattr(config.settings, "google_api_key", None)
    monkeypatch.setattr(config.settings, "google_genai_use_vertexai", False)
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
    monkeypatch.setattr(config.settings, "gemini_api_key", None)
    monkeypatch.setattr(config.settings, "vertex_ai_api_key", None)
    monkeypatch.setattr(config.settings, "google_api_key", None)
    monkeypatch.setattr(config.settings, "google_genai_use_vertexai", False)
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


def test_gemini_litellm_ids_never_openai_prefix() -> None:
    assert gemini_litellm_model_id("gemini-2.5-flash") == "gemini/gemini-2.5-flash"
    assert gemini_litellm_model_id("gemini/gemini-2.5-flash") == "gemini/gemini-2.5-flash"
    assert gemini_litellm_model_id("imagen-3.0-generate-002") == "gemini/imagen-3.0-generate-002"
    assert gemini_litellm_model_id("imagen/imagen-3.0-generate-002") == (
        "imagen/imagen-3.0-generate-002"
    )
    assert gemini_litellm_model_id("models/gemini-2.5-flash") == "gemini/gemini-2.5-flash"
    assert gemini_catalog_id("gemini/gemini-2.5-flash") == "gemini-2.5-flash"
    assert gemini_catalog_id("models/gemini-2.5-flash") == "gemini-2.5-flash"
    assert litellm_model_id(
        "gemini-2.5-flash",
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    ) == "gemini/gemini-2.5-flash"
    assert effective_api_base("gemini", "https://example.invalid") is None
    assert effective_api_base("vertex_ai", "https://should-ignore.example") == (
        "https://aiplatform.googleapis.com/v1/publishers/google"
    )
    assert effective_api_base("openai_compatible", "https://openrouter.ai/api/v1") == (
        "https://openrouter.ai/api/v1"
    )


def test_vertex_ai_express_ids_use_catalog_id_not_litellm() -> None:
    from internal.llm.resolve import VERTEX_AI_EXPRESS_API_BASE

    assert litellm_model_id(
        "gemini-2.5-flash",
        "vertex_ai",
        "https://should-ignore.example",
    ) == "gemini-2.5-flash"
    assert litellm_model_id("vertex_ai/gemini-2.5-flash", "vertex_ai", None) == (
        "gemini-2.5-flash"
    )
    assert gemini_catalog_id("publishers/google/models/gemini-2.5-flash") == (
        "gemini-2.5-flash"
    )
    assert gemini_catalog_id("vertex_ai/gemini-2.5-flash") == "gemini-2.5-flash"
    assert effective_api_base("vertex_ai", None) == VERTEX_AI_EXPRESS_API_BASE


def test_env_gemini_model_uses_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "llm_cheap_model", "gemini-2.5-flash")
    monkeypatch.setattr(config.settings, "llm_api_base", None)
    monkeypatch.setattr(config.settings, "openai_api_key", None)
    monkeypatch.setattr(config.settings, "anthropic_api_key", None)
    monkeypatch.setattr(config.settings, "gemini_api_key", "AIza-env")
    monkeypatch.setattr(config.settings, "vertex_ai_api_key", "AQ.express")
    monkeypatch.setattr(config.settings, "google_api_key", "AQ.from-sdk")
    monkeypatch.setattr(config.settings, "google_genai_use_vertexai", True)
    resolved = resolve_llm_model(ModelTier.CHEAP)
    assert resolved.provider_type == "gemini"
    assert resolved.api_key == "AIza-env"
    assert resolved.api_base is None
    assert litellm_model_id(resolved.model_id, resolved.provider_type, resolved.api_base) == (
        "gemini/gemini-2.5-flash"
    )


def test_env_vertex_ai_when_studio_key_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config
    from internal.llm.resolve import VERTEX_AI_EXPRESS_API_BASE

    monkeypatch.setattr(config.settings, "llm_cheap_model", "gemini-2.5-flash")
    monkeypatch.setattr(config.settings, "llm_api_base", None)
    monkeypatch.setattr(config.settings, "openai_api_key", None)
    monkeypatch.setattr(config.settings, "anthropic_api_key", None)
    monkeypatch.setattr(config.settings, "gemini_api_key", None)
    monkeypatch.setattr(config.settings, "vertex_ai_api_key", "AQ.express")
    resolved = resolve_llm_model(ModelTier.CHEAP)
    assert resolved.provider_type == "vertex_ai"
    assert resolved.api_key == "AQ.express"
    assert gemini_catalog_id(resolved.model_id) == "gemini-2.5-flash"
    assert effective_api_base(resolved.provider_type, resolved.api_base) == (
        VERTEX_AI_EXPRESS_API_BASE
    )


def test_env_vertex_ai_from_google_api_key_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "llm_cheap_model", "gemini-2.5-flash")
    monkeypatch.setattr(config.settings, "llm_api_base", None)
    monkeypatch.setattr(config.settings, "openai_api_key", None)
    monkeypatch.setattr(config.settings, "anthropic_api_key", None)
    monkeypatch.setattr(config.settings, "gemini_api_key", None)
    monkeypatch.setattr(config.settings, "vertex_ai_api_key", None)
    monkeypatch.setattr(config.settings, "google_api_key", "AQ.from-sdk")
    monkeypatch.setattr(config.settings, "google_genai_use_vertexai", True)
    resolved = resolve_llm_model(ModelTier.CHEAP)
    assert resolved.provider_type == "vertex_ai"
    assert resolved.api_key == "AQ.from-sdk"
    assert env_has_llm_credentials()


def test_env_google_api_key_without_flag_is_not_express(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "llm_cheap_model", "gemini-2.5-flash")
    monkeypatch.setattr(config.settings, "llm_api_base", None)
    monkeypatch.setattr(config.settings, "openai_api_key", None)
    monkeypatch.setattr(config.settings, "anthropic_api_key", None)
    monkeypatch.setattr(config.settings, "gemini_api_key", None)
    monkeypatch.setattr(config.settings, "vertex_ai_api_key", None)
    monkeypatch.setattr(config.settings, "google_api_key", "AQ.ignored")
    monkeypatch.setattr(config.settings, "google_genai_use_vertexai", False)
    resolved = resolve_llm_model(ModelTier.CHEAP)
    assert resolved.provider_type == "gemini"
    assert resolved.api_key is None
    assert not env_has_llm_credentials()


def test_env_vertex_ai_api_key_wins_over_google_api_key_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "llm_cheap_model", "gemini-2.5-flash")
    monkeypatch.setattr(config.settings, "llm_api_base", None)
    monkeypatch.setattr(config.settings, "openai_api_key", None)
    monkeypatch.setattr(config.settings, "anthropic_api_key", None)
    monkeypatch.setattr(config.settings, "gemini_api_key", None)
    monkeypatch.setattr(config.settings, "vertex_ai_api_key", "AQ.explicit")
    monkeypatch.setattr(config.settings, "google_api_key", "AQ.from-sdk")
    monkeypatch.setattr(config.settings, "google_genai_use_vertexai", True)
    resolved = resolve_llm_model(ModelTier.CHEAP)
    assert resolved.provider_type == "vertex_ai"
    assert resolved.api_key == "AQ.explicit"


def test_org_gemini_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal import config

    monkeypatch.setattr(config.settings, "llm_cheap_model", "gpt-4o-mini")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-env")
    monkeypatch.setattr(config.settings, "llm_api_base", None)
    gemini = _org(
        "gemini-2.5-flash",
        api_key="AIza-org",
        api_base="https://should-ignore.example",
        provider_type="gemini",
    )
    with llm_bundle_scope(CompanyLlmBundle(cheap=gemini)):
        resolved = resolve_llm_model(ModelTier.CHEAP)
    assert resolved.source == "org"
    assert resolved.provider_type == "gemini"
    assert resolved.api_key == "AIza-org"
    assert litellm_model_id(resolved.model_id, resolved.provider_type, resolved.api_base) == (
        "gemini/gemini-2.5-flash"
    )
