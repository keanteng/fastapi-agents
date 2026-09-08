from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.api.errors import AppError
from app.runs.models import RunMessage, RunResponse
from app.runs.registry import (
    CancelConflictError,
    RunNotFoundError,
    SseBusyError,
)
from app.runs.sse import stream_events

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    agent: str = "generalist"
    input: str = Field(..., min_length=1)
    conversation_id: str | None = None
    message_history: list[RunMessage] | None = None
    tools: list[str] | None = None
    capabilities: list[str] | None = None
    max_steps: int | None = Field(default=None, ge=1, le=20)
    metadata: dict | None = None


@router.post("", status_code=202, response_model=RunResponse)
async def create_run(body: CreateRunRequest, request: Request) -> RunResponse:
    container = request.app.state.container
    definition = container.agents.definitions.get(body.agent)
    if definition is None:
        raise AppError(
            422,
            "unknown_agent",
            f"unknown agent {body.agent!r}",
            details={"available": sorted(container.agents.definitions)},
        )
    if body.max_steps is None:
        body.max_steps = definition.default_max_steps
    record = await container.runs.create(body, container)
    return RunResponse.from_record(record)


@router.get("", response_model=list[RunResponse])
async def list_runs(request: Request) -> list[RunResponse]:
    records = await request.app.state.container.runs.list()
    return [RunResponse.from_record(record) for record in records]


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: str, request: Request) -> RunResponse:
    registry = request.app.state.container.runs
    try:
        record = await registry.get(run_id)
    except RunNotFoundError:
        raise AppError(
            404, "run_not_found", f"run {run_id} does not exist", run_id=run_id
        ) from None
    return RunResponse.from_record(record)


@router.get("/{run_id}/events")
async def stream_run_events(run_id: str, request: Request) -> EventSourceResponse:
    registry = request.app.state.container.runs
    try:
        record, replay = await registry.claim_subscriber(run_id)
    except RunNotFoundError:
        raise AppError(
            404, "run_not_found", f"run {run_id} does not exist", run_id=run_id
        ) from None
    except SseBusyError:
        raise AppError(
            409,
            "sse_busy",
            f"run {run_id} already has an SSE subscriber",
            run_id=run_id,
        ) from None
    return EventSourceResponse(
        stream_events(record, registry, replay),
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/{run_id}/cancel", status_code=202, response_model=RunResponse)
async def cancel_run(run_id: str, request: Request) -> RunResponse:
    registry = request.app.state.container.runs
    try:
        record = await registry.cancel(run_id)
    except RunNotFoundError:
        raise AppError(
            404, "run_not_found", f"run {run_id} does not exist", run_id=run_id
        ) from None
    except CancelConflictError:
        raise AppError(
            409,
            "cancel_conflict",
            f"run {run_id} is already terminal",
            run_id=run_id,
        ) from None
    return RunResponse.from_record(record)
