"""Parse + cache helpers for BYOK model-list proxy (no live network)."""

from __future__ import annotations

from uuid import uuid4

from internal.llm.probes import (
    cache_get,
    cache_put,
    capability_from_item,
    infer_capability,
    invalidate_model_list_cache,
    models_list_url,
    parse_model_list,
    reset_model_list_cache,
)
from schemas.byok import ByokModelListProxy


def test_infer_capability_image_markers() -> None:
    assert infer_capability("bytedance-seed/seedream-4.5") == ("image", "inferred")
    assert infer_capability("dall-e-3") == ("image", "inferred")
    assert infer_capability("gpt-4o") == ("chat", "inferred")


def test_capability_from_openrouter_architecture() -> None:
    chat = capability_from_item(
        {"architecture": {"modality": "text+image->text", "output_modalities": ["text"]}},
        "openai/gpt-4o",
    )
    assert chat == ("chat", "provider_metadata")
    image = capability_from_item(
        {"architecture": {"modality": "text->image", "output_modalities": ["image"]}},
        "bytedance/seedream",
    )
    assert image == ("image", "provider_metadata")


def test_parse_model_list_openai_shape() -> None:
    models = parse_model_list({"data": [{"id": "gpt-4o-mini"}, {"id": "dall-e-3"}]})
    by_id = {m.id: m for m in models}
    assert by_id["gpt-4o-mini"].capability == "chat"
    assert by_id["dall-e-3"].capability == "image"
    assert by_id["dall-e-3"].capability_source == "inferred"


def test_cache_keyed_by_provider_id() -> None:
    reset_model_list_cache()
    a, b = uuid4(), uuid4()
    payload_a = ByokModelListProxy(
        fetchable=True, models=[{"id": "org-a", "capability": "chat", "capability_source": "manual"}]
    )
    payload_b = ByokModelListProxy(
        fetchable=True, models=[{"id": "org-b", "capability": "chat", "capability_source": "manual"}]
    )
    cache_put(a, payload_a)
    cache_put(b, payload_b)
    assert cache_get(a).models[0].id == "org-a"
    assert cache_get(b).models[0].id == "org-b"
    invalidate_model_list_cache(a)
    assert cache_get(a) is None
    assert cache_get(b).models[0].id == "org-b"


def test_models_list_url_defaults() -> None:
    class P:
        provider_type = "openai"
        api_base = None

    assert models_list_url(P()) == "https://api.openai.com/v1/models"  # type: ignore[arg-type]

    class A:
        provider_type = "anthropic"
        api_base = None

    assert models_list_url(A()) == "https://api.anthropic.com/v1/models"  # type: ignore[arg-type]

    class C:
        provider_type = "openai_compatible"
        api_base = "https://openrouter.ai/api/v1"

    assert models_list_url(C()) == "https://openrouter.ai/api/v1/models"  # type: ignore[arg-type]
