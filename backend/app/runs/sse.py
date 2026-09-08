from __future__ import annotations

from collections.abc import AsyncIterator

from app.runs.events import RunEvent
from app.runs.models import RunRecord, TERMINAL_STATUSES
from app.runs.registry import RunRegistry, SSE_PING_INTERVAL


def event_frame(event: RunEvent) -> dict[str, str]:
    """sse-starlette frame dict for a run event."""
    return {"event": event.type, "data": event.model_dump_json()}


async def stream_events(
    record: RunRecord,
    registry: RunRegistry,
    replay: list[RunEvent],
    *,
    ping_interval: float = SSE_PING_INTERVAL,
) -> AsyncIterator[dict[str, str]]:
    """Yield SSE frames for a run; the terminal event is always last."""
    try:
        for event in replay:
            yield event_frame(event)
            if event.terminal:
                return
        while True:
            new_events = await registry.wait_for_events(record, ping_interval)
            if new_events:
                for event in new_events:
                    yield event_frame(event)
                    if event.terminal:
                        return
            elif record.status not in TERMINAL_STATUSES:
                ping = await registry.emit_ping(record)
                yield event_frame(ping)
    finally:
        registry.release_subscriber(record)
