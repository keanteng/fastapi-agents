from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.agents import router as agents_router
from app.api.conversations import router as conversations_router
from app.api.health import router as health_router
from app.api.runs import router as runs_router
from app.api.uploads import router as uploads_router
from app.core.security import rate_limit, require_api_key

api_router = APIRouter()
# Health probes stay unauthenticated and unthrottled so orchestrators can
# always reach them.
api_router.include_router(health_router)

_protection = [Depends(require_api_key), Depends(rate_limit)]
api_router.include_router(runs_router, dependencies=_protection)
api_router.include_router(agents_router, dependencies=_protection)
api_router.include_router(conversations_router, dependencies=_protection)
api_router.include_router(uploads_router, dependencies=_protection)
