"""Per-turn LLM credential resolution (ADR 0020).

A company bundle is preloaded in ``company_llm_scope`` (async, one DB read +
decrypt of referenced keys). Sync callers (``_base_kwargs``, ``live_harness_model``)
read the contextvar — they never query the DB.

Unbound (no scope / ``company_id is None``) or a NULL routing slot falls back
to env. A slot that points at a row whose key cannot be decrypted raises
``LlmProviderError`` at resolve time — it must not silently bill the platform key.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from internal.config import settings
from internal.llm.keys import ByokEncryptionError, decrypt_key, mask_key

logger = logging.getLogger(__name__)

Source = Literal["env", "org"]
ProviderType = Literal["openai", "anthropic", "openai_compatible"]


@dataclass(frozen=True)
class ResolvedModel:
    model_id: str
    api_key: str | None
    api_base: str | None
    provider_type: ProviderType
    source: Source
    key_last4: str | None


@dataclass(frozen=True)
class FailedOrgSlot:
    """Routing points here but the provider key could not be decrypted."""

    model_id: str


OrgSlot = ResolvedModel | FailedOrgSlot | None


@dataclass(frozen=True)
class CompanyLlmBundle:
    cheap: OrgSlot = None
    medium: OrgSlot = None
    strong: OrgSlot = None
    image: OrgSlot = None

    def has_provider(self) -> bool:
        return any(
            isinstance(slot, ResolvedModel)
            for slot in (self.cheap, self.medium, self.strong, self.image)
        )


_bundle: ContextVar[CompanyLlmBundle | None] = ContextVar("byok_llm_bundle", default=None)


def current_bundle() -> CompanyLlmBundle | None:
    return _bundle.get()


@contextmanager
def llm_bundle_scope(bundle: CompanyLlmBundle | None) -> Iterator[None]:
    """Sync test / inner hook: pin a prebuilt bundle (or None = unbound)."""
    token = _bundle.set(bundle)
    try:
        yield
    finally:
        _bundle.reset(token)


def env_has_llm_credentials() -> bool:
    return bool(
        (settings.openai_api_key or "").strip() or (settings.anthropic_api_key or "").strip()
    )


def bundle_has_credentials() -> bool:
    bundle = _bundle.get()
    return bool(bundle is not None and bundle.has_provider())


def prefix_litellm_model(model_id: str, api_base: str | None) -> str:
    """When a custom api_base is set, force the OpenAI-compatible LiteLLM client."""
    if not (api_base or "").strip():
        return model_id
    if "/" in model_id:
        return model_id
    return f"openai/{model_id}"


def _env_provider_type(model_id: str) -> ProviderType:
    if (settings.llm_api_base or "").strip():
        return "openai_compatible"
    lowered = model_id.lower()
    if "claude" in lowered or lowered.startswith("anthropic"):
        return "anthropic"
    return "openai"


def _env_api_key(provider_type: ProviderType) -> str | None:
    if provider_type == "anthropic":
        raw = (settings.anthropic_api_key or "").strip()
        return raw or None
    raw = (settings.openai_api_key or "").strip()
    return raw or None


def _env_chat(tier: str) -> ResolvedModel:
    mapping = {
        "cheap": settings.llm_cheap_model,
        "medium": settings.llm_medium_model,
        "strong": settings.llm_strong_model,
    }
    model_id = mapping[tier]
    provider_type = _env_provider_type(model_id)
    api_key = _env_api_key(provider_type)
    api_base = (settings.llm_api_base or "").strip() or None
    return ResolvedModel(
        model_id=model_id,
        api_key=api_key,
        api_base=api_base,
        provider_type=provider_type,
        source="env",
        key_last4=mask_key(api_key) if api_key else None,
    )


def _env_image() -> ResolvedModel | None:
    raw = (settings.llm_image_model or "").strip()
    if not raw:
        return None
    provider_type = _env_provider_type(raw)
    api_key = _env_api_key(provider_type)
    api_base = (settings.llm_api_base or "").strip() or None
    return ResolvedModel(
        model_id=raw,
        api_key=api_key,
        api_base=api_base,
        provider_type=provider_type,
        source="env",
        key_last4=mask_key(api_key) if api_key else None,
    )


def _tier_slot(tier: Any) -> str:
    return str(getattr(tier, "value", tier))


def _raise_decrypt_failed(model_id: str) -> None:
    from internal.llm.router import LlmProviderError

    raise LlmProviderError(
        f"Could not decrypt the org API key for model {model_id}. "
        "Check BYOK_ENCRYPTION_KEY.",
        model=model_id,
        kind="auth",
    )


def resolve_llm_model(tier: Any) -> ResolvedModel:
    slot_name = _tier_slot(tier)
    bundle = _bundle.get()
    if bundle is not None:
        slot = getattr(bundle, slot_name)
        if isinstance(slot, FailedOrgSlot):
            _raise_decrypt_failed(slot.model_id)
        if isinstance(slot, ResolvedModel):
            return slot
    return _env_chat(slot_name)


def resolve_image() -> ResolvedModel | None:
    bundle = _bundle.get()
    if bundle is not None:
        slot = bundle.image
        if isinstance(slot, FailedOrgSlot):
            _raise_decrypt_failed(slot.model_id)
        if isinstance(slot, ResolvedModel):
            return slot
    return _env_image()


def _slot_from_model(
    model: Any,
    providers: dict[uuid.UUID, Any],
    *,
    expected_capability: str,
) -> OrgSlot:
    if model is None:
        return None
    cap = (getattr(model, "capability", None) or "").strip()
    if cap and cap != expected_capability:
        logger.warning(
            "BYOK routing skipped model %s: capability %s != %s",
            model.id,
            cap,
            expected_capability,
        )
        return None
    provider = providers.get(model.provider_id)
    if provider is None:
        logger.warning("BYOK routing skipped model %s: provider missing", model.id)
        return None
    try:
        api_key = decrypt_key(provider.api_key_encrypted)
    except ByokEncryptionError:
        return FailedOrgSlot(model_id=str(model.model_id))
    ptype = str(provider.provider_type or "openai")
    if ptype not in ("openai", "anthropic", "openai_compatible"):
        ptype = "openai"
    api_base = (provider.api_base or "").strip() or None
    return ResolvedModel(
        model_id=str(model.model_id),
        api_key=api_key,
        api_base=api_base,
        provider_type=ptype,  # type: ignore[arg-type]
        source="org",
        key_last4=provider.key_last4 or mask_key(api_key),
    )


async def load_company_llm_bundle(
    db: AsyncSession,
    company_id: uuid.UUID,
) -> CompanyLlmBundle:
    from internal.memory import repos

    routing = await repos.get_byok_routing(db, company_id)
    if routing is None:
        return CompanyLlmBundle()
    ids = [
        mid
        for mid in (
            routing.cheap_model_id,
            routing.medium_model_id,
            routing.strong_model_id,
            routing.image_model_id,
        )
        if mid is not None
    ]
    models = await repos.list_byok_models_by_ids(db, company_id, ids)
    by_id = {m.id: m for m in models}
    provider_ids = list({m.provider_id for m in models})
    providers = {
        p.id: p
        for p in await repos.list_byok_providers_by_ids(db, company_id, provider_ids)
    }
    return CompanyLlmBundle(
        cheap=_slot_from_model(
            by_id.get(routing.cheap_model_id) if routing.cheap_model_id else None,
            providers,
            expected_capability="chat",
        ),
        medium=_slot_from_model(
            by_id.get(routing.medium_model_id) if routing.medium_model_id else None,
            providers,
            expected_capability="chat",
        ),
        strong=_slot_from_model(
            by_id.get(routing.strong_model_id) if routing.strong_model_id else None,
            providers,
            expected_capability="chat",
        ),
        image=_slot_from_model(
            by_id.get(routing.image_model_id) if routing.image_model_id else None,
            providers,
            expected_capability="image",
        ),
    )


@asynccontextmanager
async def company_llm_scope(
    db: AsyncSession,
    company_id: uuid.UUID | None,
) -> AsyncIterator[None]:
    bundle: CompanyLlmBundle | None = None
    if company_id is not None:
        bundle = await load_company_llm_bundle(db, company_id)
    with llm_bundle_scope(bundle):
        yield
