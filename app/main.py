"""FastAPI application factory.

Lifespan owns the shared model HTTP client lifecycle; routers are mounted per
slice (vertical slices self-contained).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.db import dispose_db, init_db
from app.core.model import get_model
from app.features.chat.router import router as chat_router
from app.features.extract.router import router as extract_router
from app.features.memory.router import router as memory_router
from app.features.skills.router import router as skills_router
from app.features.tasks.router import router as tasks_router
from app.features.tools.router import router as tools_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Touch the model so its HTTP client is created up-front; the agent's
    # async-context-manager use in services closes clients after each run.
    get_model()
    init_db()
    try:
        yield
    finally:
        await dispose_db()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agents - pydantic-ai + DeepSeek",
        version="0.1.0",
        description="Vertical-slice FastAPI server showcasing pydantic-ai with DeepSeek.",
        lifespan=lifespan,
    )
    for router in (
        chat_router,
        memory_router,
        tools_router,
        skills_router,
        tasks_router,
        extract_router,
    ):
        app.include_router(router)
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