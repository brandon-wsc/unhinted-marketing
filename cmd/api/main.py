from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cmd.api.routes.admin import router as admin_router
from cmd.api.routes.auth import router as auth_router
from cmd.api.routes.byok import router as byok_router
from cmd.api.routes.companies import router as companies_router
from cmd.api.routes.invites import router as invites_router
from cmd.api.routes.products import router as products_router
from cmd.api.routes.proposals import router as proposals_router
from cmd.api.routes.questions import router as questions_router
from cmd.api.routes.sessions import router as sessions_router
from cmd.api.routes.signals import router as signals_router
from internal.auth.rate_limit import assert_jwt_secret_safe
from internal.config import settings
from internal.llm.keys import assert_byok_encryption_key_safe
from internal.llm.recorder import drain as drain_llm_records
from internal.session.checkpointer import close_postgres_checkpointer, open_postgres_checkpointer
from internal.session.graph import build_session_graph, set_session_graph
from internal.session.trace import drain as drain_node_steps


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool, checkpointer = await open_postgres_checkpointer()
    graph = build_session_graph(checkpointer=checkpointer)
    set_session_graph(graph)
    app.state.checkpoint_pool = pool
    app.state.checkpointer = checkpointer
    app.state.session_graph = graph
    from internal.session.semantic_gate import start_semantic_router_warmup

    start_semantic_router_warmup()
    try:
        yield
    finally:
        set_session_graph(None)
        await drain_llm_records()
        await drain_node_steps()
        await close_postgres_checkpointer(pool)


def create_app(*, lifespan_fn: Any = lifespan) -> FastAPI:
    """Build the API app. Tests pass a noop lifespan to skip Postgres checkpointer."""
    assert_jwt_secret_safe()
    assert_byok_encryption_key_safe()
    application = FastAPI(
        title="Unhinted Marketing API",
        version="0.1.0",
        lifespan=lifespan_fn,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # All public JSON/SSE routes live under /api (ADR 0006) so the SPA
    # owns every other same-origin path (e.g. document /admin).
    application.include_router(auth_router, prefix="/api")
    application.include_router(signals_router, prefix="/api")
    application.include_router(questions_router, prefix="/api")
    application.include_router(companies_router, prefix="/api")
    application.include_router(byok_router, prefix="/api")
    application.include_router(invites_router, prefix="/api")
    application.include_router(products_router, prefix="/api")
    application.include_router(proposals_router, prefix="/api")
    application.include_router(sessions_router, prefix="/api")
    application.include_router(admin_router, prefix="/api")

    @application.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
