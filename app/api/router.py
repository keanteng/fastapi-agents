from __future__ import annotations

from fastapi import APIRouter

from app.api.agents import router as agents_router
from app.api.runs import router as runs_router

api_router = APIRouter()
api_router.include_router(runs_router)
api_router.include_router(agents_router)
