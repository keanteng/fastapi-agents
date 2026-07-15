"""Tasks slice routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.features.tasks.schemas import TasksRequest, TasksResponse
from app.features.tasks.service import run_task

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.post("", response_model=TasksResponse)
async def tasks(req: TasksRequest) -> TasksResponse:
    output, steps, usage = await run_task(req.goal, req.max_steps)
    return TasksResponse(output=output, steps=steps, usage=usage)