"""LiteLLM model tiers per ROADMAP LLM Task Routing (nodes call resolve_model later)."""

from internal.llm.router import ModelTier

NODE_MODEL_TIERS: dict[str, ModelTier | None] = {
    "route_intent": ModelTier.CHEAP,
    "chat": ModelTier.CHEAP,
    "ack_confirm": ModelTier.CHEAP,
    "trend_searcher": ModelTier.CHEAP,
    "brainstormer": ModelTier.MEDIUM,
    "executor_post": ModelTier.MEDIUM,
    "edit_copy": ModelTier.MEDIUM,
    "executor_image_plan": ModelTier.MEDIUM,
    "reviewer": ModelTier.STRONG,
    "load_context": None,
    "grounding_check": None,
    "executor_image_gen": None,  # worker dispatch; no LLM
    "persist_preview": None,
}
