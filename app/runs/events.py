from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.runs.models import ErrorBody, RunArtifact, RunStep, RunUsage

TERMINAL_EVENT_TYPES = frozenset(
    {"response.completed", "response.failed", "run.cancelled"}
)


class RunEvent(BaseModel):
    type: str
    run_id: str
    sequence: int
    created_at: datetime
    data: dict[str, Any]

    @property
    def terminal(self) -> bool:
        return self.type in TERMINAL_EVENT_TYPES


def created_data(
    agent: str, conversation_id: str | None, input_text: str
) -> dict[str, Any]:
    return {"agent": agent, "conversation_id": conversation_id, "input": input_text}


def delta_data(delta: str) -> dict[str, Any]:
    return {"delta": delta}


def done_data(text: str) -> dict[str, Any]:
    return {"text": text}


def step_data(step: RunStep) -> dict[str, Any]:
    return {"step": step.model_dump(mode="json")}


def completed_data(
    status: str, usage: RunUsage | None, artifacts: list[RunArtifact]
) -> dict[str, Any]:
    return {
        "status": status,
        "usage": usage.model_dump(mode="json") if usage else {},
        "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
    }


def failed_data(error: ErrorBody) -> dict[str, Any]:
    return {"error": error.model_dump(mode="json")}


def cancelled_data() -> dict[str, Any]:
    return {"error": None}


def ping_data() -> dict[str, Any]:
    return {"t": datetime.now(timezone.utc).isoformat()}
