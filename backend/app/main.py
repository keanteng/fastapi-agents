"""FastAPI application factory.

Lifespan builds the shared ``AppContainer`` (config, LLM model, prompt engine,
agent registry, run registry) and the DB pool; middleware is registered
centrally in ``core.middleware``; error handlers in ``api.errors``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.router import api_router
from app.core.config import settings
from app.core.container import build_container, close_container
from app.core.db import dispose_db, init_db
from app.core.logging import configure_logging
from app.core.middleware import register_middleware
from app.core.observability import setup_tracing
from app.documents.janitor import upload_janitor_loop

configure_logging(json_logs=settings.log_json)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Build shared singletons (touching the model creates its HTTP client
    # up-front; agents close their own clients after each run).
    container = build_container()
    _app.state.container = container
    init_db()
    # Runs left pending/running by a previous process can never resume: fail
    # them so clients get a terminal status instead of polling forever.
    try:
        await container.runs.reconcile()
    except Exception as exc:  # noqa: BLE001 - surface an actionable message
        logger.error(
            "startup reconciliation failed (%s). The database schema is "
            "probably out of date - run `uv run alembic upgrade head`.",
            exc.__class__.__name__,
        )
        raise
    janitor = (
        asyncio.create_task(upload_janitor_loop())
        if settings.upload_ttl_seconds > 0
        else None
    )
    try:
        yield
    finally:
        if janitor is not None:
            janitor.cancel()
            try:
                await janitor
            except asyncio.CancelledError:
                pass
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
    setup_tracing(app)
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
