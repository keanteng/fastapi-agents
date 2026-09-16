from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.core import metrics
from app.core.config import settings
from app.core.logging import set_request_id

logger = logging.getLogger(__name__)

PROCESS_TIME_HEADER = "X-Process-Time-Ms"
REQUEST_ID_HEADER = "X-Request-ID"


def register_middleware(app: FastAPI) -> None:
    """Attach CORS, GZip and the request-id/process-time middleware to ``app``."""
    if "*" in settings.cors_origins and settings.auth_enabled:
        logger.warning(
            "CORS_ORIGINS is '*' while AUTH_ENABLED is true; "
            "set explicit origins before exposing this API"
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER, PROCESS_TIME_HEADER],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.middleware("http")
    async def observability_middleware(request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        set_request_id(request_id)
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
            duration = time.perf_counter() - started_at
            duration_ms = duration * 1000
            response.headers[PROCESS_TIME_HEADER] = f"{duration_ms:.2f}"
            response.headers[REQUEST_ID_HEADER] = request_id
            if settings.metrics_enabled:
                route = getattr(request.scope.get("route"), "path", request.url.path)
                metrics.observe_http(
                    request.method, route, response.status_code, duration
                )
            logger.info(
                "HTTP %s %s -> %s (%0.2f ms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            return response
        finally:
            set_request_id(None)
