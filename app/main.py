"""FastAPI application factory.

Lifespan builds the shared ``AppContainer`` (config, LLM model, prompt engine)
and the DB pool; middleware is registered centrally in ``core.middleware``.
Routers are mounted per slice (vertical slices self-contained).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings
from app.core.container import build_container, close_container
from app.core.db import dispose_db, init_db
from app.core.middleware import register_middleware


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Build shared singletons (touching the model creates its HTTP client
    # up-front; agents close their own clients after each run).
    container = build_container()
    _app.state.container = container
    init_db()
    try:
        yield
    finally:
        await dispose_db()
        close_container()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agents - pydantic-ai + DeepSeek",
        version="0.1.0",
        description="Vertical-slice FastAPI server showcasing pydantic-ai with DeepSeek.",
        lifespan=lifespan,
    )
    register_middleware(app)
    app.include_router(api_router)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
