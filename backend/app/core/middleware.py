from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.core.config import settings

logger = logging.getLogger(__name__)

PROCESS_TIME_HEADER = "X-Process-Time-Ms"


def register_middleware(app: FastAPI) -> None:
    """Attach CORS, GZip and the process-time middleware to ``app``."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.middleware("http")
    async def process_time_middleware(request: Request, call_next) -> Response:
        started_at = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started_at) * 1000
        response.headers[PROCESS_TIME_HEADER] = f"{duration_ms:.2f}"
        logger.info(
            "HTTP %s %s -> %s (%0.2f ms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
