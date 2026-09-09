from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.runs.events import RunEvent

EVENT_LOG_MAXLEN = 10_000


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None
    run_id: str | None = None


class RunStep(BaseModel):
    index: int = 0
    type: Literal["tool_call", "message", "progress"]
    name: str
    summary: str
    result: str | None = None
    tool_call_id: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class RunArtifact(BaseModel):
    name: str
    kind: Literal["text", "structured_output", "error"]
    data: Any = None


class RunUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0
    tool_calls: int = 0

    @classmethod
    def from_pai(cls, usage: Any) -> "RunUsage":
        return cls(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            requests=getattr(usage, "requests", 0) or 0,
            tool_calls=getattr(usage, "tool_calls", 0) or 0,
        )


class RunMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class RunRecord:
    """Mutable in-memory state for one run.

    All mutations happen under the ``RunRegistry`` lock. ``RunEvent``
    instances live in ``events`` (a bounded deque) for SSE replay.
    """

    def __init__(
        self,
        *,
        run_id: str,
        agent: str,
        conversation_id: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.agent = agent
        self.conversation_id = conversation_id
        self.metadata: dict | None = None
        self.status: RunStatus = RunStatus.PENDING
        self.created_at: datetime = datetime.now(timezone.utc)
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.steps: list[RunStep] = []
        self.artifacts: list[RunArtifact] = []
        self.usage: RunUsage | None = None
        self.error: ErrorBody | None = None
        self.note: str | None = None
        self.task: asyncio.Task | None = None
        self.events: deque["RunEvent"] = deque(maxlen=EVENT_LOG_MAXLEN)
        self.event_ready: asyncio.Event = asyncio.Event()
        self.seq_counter: int = 0
        self.sse_claimed: bool = False
        self.sse_index: int = 0


class RunResponse(BaseModel):
    run_id: str
    agent: str
    status: RunStatus
    conversation_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    steps: list[RunStep] = Field(default_factory=list)
    artifacts: list[RunArtifact] = Field(default_factory=list)
    usage: RunUsage | None = None
    error: ErrorBody | None = None
    note: str | None = None

    @classmethod
    def from_record(cls, record: RunRecord) -> "RunResponse":
        return cls(
            run_id=record.run_id,
            agent=record.agent,
            status=record.status,
            conversation_id=record.conversation_id,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            steps=list(record.steps),
            artifacts=list(record.artifacts),
            usage=record.usage,
            error=record.error,
            note=record.note,
        )
