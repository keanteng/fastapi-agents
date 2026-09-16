from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.runs.models import (
    ErrorBody,
    RunArtifact,
    RunRecord,
    RunStatus,
    RunStep,
    RunUsage,
)


def _now() -> datetime:
    return datetime.now(UTC)


class RunRow(Base):
    """Persisted snapshot of a run (source of truth across restarts)."""

    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tools: Mapped[list | None] = mapped_column(JSON, nullable=True)
    capabilities: Mapped[list | None] = mapped_column(JSON, nullable=True)
    max_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    steps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    artifacts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


Index("ix_runs_created_at", RunRow.created_at)


def row_from_record(record: RunRecord) -> RunRow:
    return RunRow(
        run_id=record.run_id,
        agent=record.agent,
        status=record.status.value,
        conversation_id=record.conversation_id,
        input=record.input,
        tools=record.tools,
        capabilities=record.capabilities,
        max_steps=record.max_steps,
        run_metadata=record.metadata,
        idempotency_key=record.idempotency_key,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        steps=[step.model_dump(mode="json") for step in record.steps],
        artifacts=[a.model_dump(mode="json") for a in record.artifacts],
        usage=record.usage.model_dump(mode="json") if record.usage else None,
        error=record.error.model_dump(mode="json") if record.error else None,
        note=record.note,
    )


def _json_list(value: Any) -> list:
    return list(value) if isinstance(value, list) else []


def _aware(value: datetime | None) -> datetime | None:
    """Normalise a possibly-naive DB datetime to a UTC-aware one."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def record_from_row(row: RunRow) -> RunRecord:
    record = RunRecord(
        run_id=row.run_id,
        agent=row.agent,
        conversation_id=row.conversation_id,
    )
    record.status = RunStatus(row.status)
    record.input = row.input or ""
    record.tools = _json_list(row.tools) or None
    record.capabilities = _json_list(row.capabilities) or None
    record.max_steps = row.max_steps
    record.metadata = row.run_metadata
    record.idempotency_key = row.idempotency_key
    record.created_at = _aware(row.created_at) or _now()
    record.started_at = _aware(row.started_at)
    record.finished_at = _aware(row.finished_at)
    steps = [RunStep.model_validate(step) for step in _json_list(row.steps)]
    for step in steps:
        step.started_at = _aware(step.started_at) or step.started_at
        step.finished_at = _aware(step.finished_at)
    record.steps = steps
    record.artifacts = [
        RunArtifact.model_validate(a) for a in _json_list(row.artifacts)
    ]
    record.usage = RunUsage.model_validate(row.usage) if row.usage else None
    record.error = ErrorBody.model_validate(row.error) if row.error else None
    record.note = row.note
    return record
