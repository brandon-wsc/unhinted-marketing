from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cmd.api.routes.auth import router as auth_router
from cmd.api.routes.questions import router as questions_router
from cmd.api.routes.sessions import router as sessions_router
from cmd.api.routes.signals import router as signals_router
from internal.config import settings
from internal.session.checkpointer import close_postgres_checkpointer, open_postgres_checkpointer
from internal.session.graph import build_session_graph, set_session_graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool, checkpointer = await open_postgres_checkpointer()
    graph = build_session_graph(checkpointer=checkpointer)
    set_session_graph(graph)
    app.state.checkpoint_pool = pool
    app.state.checkpointer = checkpointer
    app.state.session_graph = graph
    try:
        yield
    finally:
        set_session_graph(None)
        await close_postgres_checkpointer(pool)


app = FastAPI(
    title="Unhinted Marketing API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(signals_router)
app.include_router(questions_router)
app.include_router(sessions_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
