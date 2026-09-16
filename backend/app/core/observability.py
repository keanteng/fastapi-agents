from __future__ import annotations

import logging

from fastapi import FastAPI

from app.core.config import settings

logger = logging.getLogger(__name__)


def setup_tracing(app: FastAPI) -> None:
    """Optionally wire OpenTelemetry tracing via logfire.

    Disabled unless ``OTEL_ENABLED=true``. Logfire speaks OTLP, so this
    exports to any OpenTelemetry collector without further configuration.
    """
    if not settings.otel_enabled:
        return
    try:
        import logfire

        logfire.configure()
        logfire.instrument_fastapi(app)
        logfire.instrument_pydantic_ai()
        logfire.instrument_httpx()
    except Exception:  # noqa: BLE001 - tracing must never break serving
        logger.exception("failed to initialise tracing; continuing without it")
