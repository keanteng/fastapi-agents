"""FastAPI application factory.

Lifespan builds the shared ``AppContainer`` (config, LLM model, prompt engine,
agent registry, run registry) and the DB pool; middleware is registered
centrally in ``core.middleware``; error handlers in ``api.errors``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.router import api_router
from app.core.config import settings
from app.core.container import build_container, close_container
from app.core.db import dispose_db, init_db
from app.core.middleware import register_middleware

logging.basicConfig(level=logging.INFO)


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
        # Cancel any in-flight runs; streams close without a terminal event.
        await container.runs.shutdown()
        await dispose_db()
        close_container()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agents - pydantic-ai + DeepSeek",
        version="0.1.0",
        description="Run-centric FastAPI server showcasing pydantic-ai with DeepSeek.",
        lifespan=lifespan,
    )
    register_middleware(app)
    register_error_handlers(app)
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
