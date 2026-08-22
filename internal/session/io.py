"""Structured I/O for session LLM nodes."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ResearchFlags(BaseModel):
    """Side channel on route_intent (ADR 0009) — does not replace graph_intent."""

    need_facts: bool = False
    ambiguous: bool = False
    ask_clarify: bool = False
    entity_surface: str = ""
    rationale: str = ""
    # Product catalog path (COLLECT / SESSION)
    need_product: bool = False
    sell_intent: Literal["explicit", "implicit", "none"] = "none"
    product_surface: str = ""


class IntentRoute(BaseModel):
    intent: Literal["chat", "start", "revise", "confirm_intent"]
    rationale: str = ""
    research: ResearchFlags = Field(default_factory=ResearchFlags)


class LlmJsonModel(BaseModel):
    """Adapter for LLM JSON: ``null`` / extra keys must not fail the whole payload.

    Models emit null for optional fields and extra keys. Drop nulls so field
    defaults apply; ignore unknown keys. Semantic mismatches (wrong enum, missing
    required fields) still fail validation.
    """

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def omit_nulls(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


class QueryGenOut(LlmJsonModel):
    """Atomic web queries — prefer search_queries; search_query kept for single-query compat."""

    search_query: str = Field(default="", max_length=200)
    search_queries: list[str] = Field(default_factory=list, max_length=3)
    topic: Literal["general", "news", "finance"] = "news"
    time_range: Literal["day", "week", "month", "year"] | None = "week"

    @field_validator("search_queries", mode="before")
    @classmethod
    def drop_null_query_items(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, list):
            return [q for q in v if isinstance(q, str) and q.strip()][:3]
        return v

    def atomic_queries(self) -> list[str]:
        qs = [q.strip() for q in self.search_queries if isinstance(q, str) and q.strip()]
        if not qs and self.search_query.strip():
            qs = [self.search_query.strip()]
        # Dedupe, cap length
        out: list[str] = []
        seen: set[str] = set()
        for q in qs[:3]:
            q = q[:200]
            key = q.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(q)
        return out


class TrendRank(BaseModel):
    ranked_signal_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class BriefOut(BaseModel):
    can_do: list[str] = Field(default_factory=list)
    cannot_do: list[str] = Field(default_factory=list)
    angles: list[str] = Field(default_factory=list)
    persona: str | None = None
    summary: str = ""


class DraftOut(BaseModel):
    caption: str
    hashtags: list[str] = Field(default_factory=list)
    cta: str = ""
    source_signal_ids: list[str] = Field(default_factory=list)


class ReviewOut(BaseModel):
    passed: bool
    feedback: str = ""
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ImagePlanPanel(BaseModel):
    """One beat in a multi-panel comic (folded into a single image prompt)."""

    index: int = Field(ge=1, le=4)
    beat: str = Field(min_length=1, max_length=400)


class ImagePlanOut(BaseModel):
    prompt: str
    format: Literal["single", "comic_4panel"] = "single"
    composition: str = ""
    style: str = ""
    avoid: list[str] = Field(default_factory=list)
    panels: list[ImagePlanPanel] = Field(default_factory=list)


class EditOut(BaseModel):
    caption: str
    hashtags: list[str] = Field(default_factory=list)
    cta: str = ""
    need_image: bool = False
    source_signal_ids: list[str] = Field(default_factory=list)
