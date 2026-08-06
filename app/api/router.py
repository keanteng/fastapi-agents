from __future__ import annotations

from fastapi import APIRouter

from app.api.agents import router as agents_router
from app.api.runs import router as runs_router
from app.features.chat.router import router as chat_router
from app.features.extract.router import router as extract_router
from app.features.memory.router import router as memory_router
from app.features.skills.router import router as skills_router
from app.features.tasks.router import router as tasks_router
from app.features.tools.router import router as tools_router

api_router = APIRouter()
api_router.include_router(runs_router)
api_router.include_router(agents_router)
# Legacy routers stay mounted until Task 10 deletes the features slice.
api_router.include_router(chat_router)
api_router.include_router(memory_router)
api_router.include_router(tools_router)
api_router.include_router(skills_router)
api_router.include_router(tasks_router)
api_router.include_router(extract_router)
