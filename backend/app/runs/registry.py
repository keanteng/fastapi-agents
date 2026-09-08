from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from app.runs.events import RunEvent, cancelled_data, ping_data, step_data
from app.runs.models import (
    RunRecord,
    RunStatus,
    TERMINAL_STATUSES,
)

SSE_PING_INTERVAL = 15.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RunNotFoundError(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id} does not exist")
        self.run_id = run_id


class CancelConflictError(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id} is already terminal")
        self.run_id = run_id


class SseBusyError(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id} already has an SSE subscriber")
        self.run_id = run_id


class RunRegistry:
    """In-memory run registry. All mutations happen under a single lock."""

    def __init__(self) -> None:
        self._records: dict[str, RunRecord] = {}
        self.lock = asyncio.Lock()

    def register(self, record: RunRecord) -> None:
        """Insert a pre-built record (tests and direct callers)."""
        self._records[record.run_id] = record

    async def create(self, request: Any, container: Any) -> RunRecord:
        """Create a pending run and schedule its background task."""
        record = RunRecord(
            run_id=uuid.uuid4().hex,
            agent=request.agent,
            conversation_id=request.conversation_id,
        )
        record.metadata = request.metadata
        async with self.lock:
            self._records[record.run_id] = record
        from app.runs.runner import execute_run  # local import avoids a cycle

        task = asyncio.create_task(execute_run(record, self, container, request))
        record.task = task
        return record

    async def get(self, run_id: str) -> RunRecord:
        async with self.lock:
            record = self._records.get(run_id)
        if record is None:
            raise RunNotFoundError(run_id)
        return record

    async def list(self) -> list[RunRecord]:
        async with self.lock:
            return sorted(
                self._records.values(),
                key=lambda r: r.created_at,
                reverse=True,
            )

    async def cancel(self, run_id: str) -> RunRecord:
        """Transition to ``cancelled`` and cancel the run's task (§5.3)."""
        async with self.lock:
            record = self._records.get(run_id)
            if record is None:
                raise RunNotFoundError(run_id)
            if record.status in TERMINAL_STATUSES:
                raise CancelConflictError(run_id)
            was_running = record.status == RunStatus.RUNNING
            record.status = RunStatus.CANCELLED
            record.finished_at = _now()
            task = record.task
            if not was_running:
                # Task never started: no runner to emit the terminal event.
                self._emit_locked(record, "run.cancelled", cancelled_data())
        if task is not None:
            task.cancel()
        return record

    async def shutdown(self) -> None:
        """Cancel every in-flight run task (app shutdown)."""
        async with self.lock:
            tasks = [
                record.task
                for record in self._records.values()
                if record.task is not None and not record.task.done()
            ]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------ #
    # Event log
    # ------------------------------------------------------------------ #

    async def emit(
        self, record: RunRecord, event_type: str, data: dict[str, Any]
    ) -> RunEvent:
        async with self.lock:
            return self._emit_locked(record, event_type, data)

    def _emit_locked(
        self, record: RunRecord, event_type: str, data: dict[str, Any]
    ) -> RunEvent:
        record.seq_counter += 1
        sequence = record.seq_counter
        event = RunEvent(
            type=event_type,
            run_id=record.run_id,
            sequence=sequence,
            created_at=_now(),
            data=data,
        )
        self._append_event(record, event)
        record.event_ready.set()
        return event

    def _append_event(self, record: RunRecord, event: RunEvent) -> None:
        log = record.events
        maxlen = log.maxlen
        if maxlen is None:
            log.append(event)
            return
        if event.terminal:
            while len(log) >= maxlen and not log[0].terminal:
                log.popleft()
        elif len(log) >= maxlen:
            log.popleft()
        log.append(event)

    async def add_step(self, record: RunRecord, step: Any) -> None:
        """Append a step to the record and emit its ``run.step`` event."""
        async with self.lock:
            step.index = len(record.steps) + 1
            record.steps.append(step)
            self._emit_locked(record, "run.step", step_data(step))

    async def add_progress(self, record: RunRecord, message: str) -> None:
        """Record a transient pipeline progress line as a ``progress`` step.

        Long-running tools (e.g. document compliance) call this to stream a
        lightweight, human-readable status tick into the ``run.step`` stream.
        """
        from app.runs.models import RunStep

        now = _now()
        step = RunStep(
            index=0,
            type="progress",
            name="progress",
            summary=message[:200],
            result=None,
            started_at=now,
            finished_at=now,
        )
        await self.add_step(record, step)

    async def emit_ping(self, record: RunRecord) -> RunEvent:
        """Build a keepalive ping event (not stored in the event log)."""
        async with self.lock:
            record.seq_counter += 1
            sequence = record.seq_counter
            return RunEvent(
                type="ping",
                run_id=record.run_id,
                sequence=sequence,
                created_at=_now(),
                data=ping_data(),
            )

    # ------------------------------------------------------------------ #
    # SSE subscriber contract (§4.5/§9.9): one subscriber, one-shot claim.
    # ------------------------------------------------------------------ #

    async def claim_subscriber(self, run_id: str) -> tuple[RunRecord, list[RunEvent]]:
        """Claim the single SSE subscriber slot; returns buffered events."""
        async with self.lock:
            record = self._records.get(run_id)
            if record is None:
                raise RunNotFoundError(run_id)
            if record.sse_claimed:
                raise SseBusyError(run_id)
            record.sse_claimed = True
            record.sse_index = len(record.events)
            replay = list(record.events)
        return record, replay

    async def wait_for_events(
        self, record: RunRecord, timeout: float
    ) -> list[RunEvent]:
        """Wait up to ``timeout`` for new events; return them (or [] on timeout)."""
        async with self.lock:
            new = self._new_events(record)
            if new:
                return new
            record.event_ready.clear()
        try:
            await asyncio.wait_for(record.event_ready.wait(), timeout=timeout)
        except TimeoutError:
            return []
        async with self.lock:
            return self._new_events(record)

    def _new_events(self, record: RunRecord) -> list[RunEvent]:
        index = record.sse_index
        events = list(record.events)[index:]
        if events:
            record.sse_index = index + len(events)
        return events

    def release_subscriber(self, record: RunRecord) -> None:
        """Called when the SSE generator ends.

        The claim is one-shot: ``sse_claimed`` stays set so later subscribers
        are rejected with ``409 sse_busy``; clients must poll for state.
        """
        return None
