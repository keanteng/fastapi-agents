from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.api.errors import AppError
from app.core.config import settings
from app.core.db import get_session_maker
from app.core.metrics import registry

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: str


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Liveness probe: the process is up and serving."""
    return HealthOut(status="ok")


@router.get("/ready", response_model=HealthOut)
async def ready() -> HealthOut:
    """Readiness probe: the process can serve traffic (DB reachable)."""
    session = get_session_maker()()
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - readiness reports, never raises
        raise AppError(
            503, "not_ready", f"database unavailable: {exc.__class__.__name__}"
        ) from None
    finally:
        await session.close()
    return HealthOut(status="ready")


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus exposition endpoint (disabled via ``METRICS_ENABLED=false``)."""
    if not settings.metrics_enabled:
        raise AppError(404, "metrics_disabled", "metrics are disabled")
    return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
