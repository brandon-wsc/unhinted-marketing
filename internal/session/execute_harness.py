"""Pydantic AI inner loop for executor_post (ADR 0019).

Narrow agent: typed DraftOut. Publish-class tools are never registered.
Graph vertices stay unchanged; Confirm remains HTTP.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, RunCancelled
from pydantic_ai.models import Model

from internal.llm.recorder import mark_last_call, track
from internal.llm.router import LlmProviderError, ModelTier
from internal.session import harness as H
from internal.session import prompts
from internal.session.io import DraftOut, omit_nulls
from internal.session.tiers import NODE_MODEL_TIERS
from schemas.tools import QueryMarketTrendsResponse

logger = logging.getLogger(__name__)

EXECUTE_TOOL_NAMES = frozenset({"query_market_trends"})

_model_override: Model | None = None


@dataclass
class ExecuteDeps:
    company_id: uuid.UUID | None = None


def set_execute_model_override(model: Model | None) -> None:
    """Test hook: inject TestModel / FunctionModel. Pass None to restore live."""
    global _model_override
    _model_override = model


async def query_market_trends(
    ctx: RunContext[ExecuteDeps],
    region: str = "HK",
    limit: int = 20,
) -> QueryMarketTrendsResponse:
    """Read-only lookup of recent Hong Kong market signals from PostgreSQL."""
    del ctx
    return await H.lookup_market_trends(region, limit)


def build_execute_agent(
    *,
    model: Model,
    extra_tools: Sequence[Any] = (),
) -> Agent[ExecuteDeps, DraftOut]:
    tools: list[Any] = [query_market_trends, *extra_tools]
    return Agent(
        model,
        deps_type=ExecuteDeps,
        output_type=DraftOut,
        system_prompt=prompts.EXECUTOR_POST,
        tools=tools,
        name="session_execute",
        end_strategy="exhaustive",
    )


def _usage_of(result: Any) -> Any:
    usage = getattr(result, "usage", None)
    return usage() if callable(usage) else usage


async def run_executor_post_agent(
    user_prompt: str,
    deps: ExecuteDeps,
) -> DraftOut | None:
    """Run the execute agent; return DraftOut or None on parse miss."""
    model = _model_override or H.live_harness_model(
        NODE_MODEL_TIERS["executor_post"] or ModelTier.MEDIUM
    )
    agent = build_execute_agent(model=model)
    parsed: DraftOut | None = None
    with track(
        kind="chat_json",
        tier=NODE_MODEL_TIERS["executor_post"],
        model=H._model_label(model),
        system=prompts.EXECUTOR_POST,
        user=user_prompt,
    ) as rec:
        try:
            result = await agent.run(user_prompt, deps=deps)
            rec.set_usage(_usage_of(result))
            output = result.output
            if isinstance(output, DraftOut):
                parsed = DraftOut.model_validate(omit_nulls(output.model_dump()))
            elif isinstance(output, dict):
                parsed = DraftOut.model_validate(omit_nulls(output))
            else:
                parsed = DraftOut.model_validate(omit_nulls({"caption": str(output)}))
            rec.response_text = parsed.model_dump_json()
        except asyncio.CancelledError:
            raise
        except RunCancelled as exc:
            raise asyncio.CancelledError from exc
        except (ModelHTTPError, ModelAPIError) as exc:
            raise H._wrap_provider_error(exc) from exc
        except LlmProviderError:
            raise
        except Exception:
            mark_last_call(parse_ok=False, fallback_used=True)
            logger.exception("executor_post agent failed")
            return None
        if not (parsed.caption or "").strip():
            mark_last_call(parse_ok=False, fallback_used=True)
            return None
        mark_last_call(parse_ok=True)
        return parsed
