"""Export OpenAPI + JSON Schema contract mirrors under docs/.

Usage (repo root, after `pip install -e ".[dev]"`):

    python -m scripts.export_contracts
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from schemas.contracts import (
    EVENT_PAYLOAD_MODELS,
    AgentProgressData,
    DraftCopy,
    PreviewUpdatedData,
    SessionBriefData,
    SessionEventType,
)
from schemas.tools import (
    PublishSocialPostRequest,
    PublishSocialPostResponse,
    QueryMarketTrendsRequest,
    QueryMarketTrendsResponse,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / "docs" / "contracts"
OPENAPI_PATH = ROOT / "docs" / "openapi.json"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema(mode="serialization", by_alias=True)


def export_json_schemas() -> list[Path]:
    written: list[Path] = []
    models: dict[str, type[BaseModel]] = {
        "draft-copy": DraftCopy,
        "preview-updated": PreviewUpdatedData,
        "session-brief": SessionBriefData,
        "agent-progress": AgentProgressData,
        "query-market-trends-request": QueryMarketTrendsRequest,
        "query-market-trends-response": QueryMarketTrendsResponse,
        "publish-social-post-request": PublishSocialPostRequest,
        "publish-social-post-response": PublishSocialPostResponse,
    }
    for name, model in models.items():
        path = CONTRACTS_DIR / f"{name}.schema.json"
        _write_json(path, _schema(model))
        written.append(path)

    catalog = {
        "title": "Session SSE / turn event catalog",
        "description": (
            "Known event types for session bus (ADR 0002). "
            "payload_schema is null when the data object is empty or not yet a tight DTO."
        ),
        "events": [
            {
                "type": t.value,
                "payload_model": (
                    EVENT_PAYLOAD_MODELS[t].__name__ if EVENT_PAYLOAD_MODELS[t] else None
                ),
            }
            for t in SessionEventType
        ],
    }
    catalog_path = CONTRACTS_DIR / "session-events.catalog.json"
    _write_json(catalog_path, catalog)
    written.append(catalog_path)
    return written


def export_openapi() -> Path:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager

    from fastapi import FastAPI

    from cmd.api.main import create_app

    @asynccontextmanager
    async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield

    app = create_app(lifespan_fn=_noop_lifespan)
    _write_json(OPENAPI_PATH, app.openapi())
    return OPENAPI_PATH


def main() -> None:
    paths = export_json_schemas()
    openapi = export_openapi()
    print(f"Wrote {len(paths)} contract files under {CONTRACTS_DIR}")
    print(f"Wrote OpenAPI → {openapi}")


if __name__ == "__main__":
    main()
