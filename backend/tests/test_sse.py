from __future__ import annotations

import asyncio

from app.runs.events import RunEvent, completed_data, created_data, done_data
from app.runs.models import RunRecord
from app.runs.registry import RunRegistry
from app.runs.sse import event_frame, stream_events


def test_event_frame_format() -> None:
    from datetime import datetime, timezone

    event = RunEvent(
        type="response.created",
        run_id="r",
        sequence=1,
        created_at=datetime.now(timezone.utc),
        data={},
    )
    frame = event_frame(event)
    assert frame == {"event": "response.created", "data": event.model_dump_json()}


async def test_stream_replays_buffered_events() -> None:
    registry = RunRegistry()
    record = RunRecord(run_id="r1", agent="generalist")
    registry.register(record)
    await registry.emit(
        record, "response.created", created_data("generalist", None, "hi")
    )
    await registry.emit(record, "response.output_text.done", done_data("hi"))
    await registry.emit(
        record, "response.completed", completed_data("completed", None, [])
    )

    _claimed, replay = await registry.claim_subscriber("r1")
    frames = [frame async for frame in stream_events(record, registry, replay)]
    events = [frame["event"] for frame in frames]
    assert events == [
        "response.created",
        "response.output_text.done",
        "response.completed",
    ]


async def test_stream_waits_for_late_events() -> None:
    registry = RunRegistry()
    record = RunRecord(run_id="r2", agent="generalist")
    registry.register(record)
    await registry.emit(
        record, "response.created", created_data("generalist", None, "hi")
    )

    async def consume() -> list:
        _claimed, replay = await registry.claim_subscriber("r2")
        frames = []
        async for frame in stream_events(record, registry, replay):
            frames.append(frame)
        return frames

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    await registry.emit(record, "response.output_text.done", done_data("done"))
    await registry.emit(
        record, "response.completed", completed_data("completed", None, [])
    )
    frames = await task
    events = [frame["event"] for frame in frames]
    # response.created was buffered before the claim, so it is replayed first;
    # the stream then waits for and delivers the late done/completed events.
    assert events == [
        "response.created",
        "response.output_text.done",
        "response.completed",
    ]


async def test_stream_emits_ping_while_running() -> None:
    registry = RunRegistry()
    record = RunRecord(run_id="r3", agent="generalist")
    registry.register(record)
    await registry.emit(
        record, "response.created", created_data("generalist", None, "hi")
    )

    async def consume() -> list:
        _claimed, replay = await registry.claim_subscriber("r3")
        frames = []
        async for frame in stream_events(record, registry, replay, ping_interval=0.05):
            frames.append(frame)
            if len(frames) == 2:
                break
        return frames

    frames = await consume()
    events = [frame["event"] for frame in frames]
    assert events[0] == "response.created"
    assert events[1] == "ping"
    assert "t" in frames[1]["data"]


async def test_stream_does_not_ping_after_terminal() -> None:
    registry = RunRegistry()
    record = RunRecord(run_id="r4", agent="generalist")
    registry.register(record)
    await registry.emit(
        record, "response.created", created_data("generalist", None, "hi")
    )
    await registry.emit(
        record, "response.completed", completed_data("completed", None, [])
    )

    _claimed, replay = await registry.claim_subscriber("r4")
    frames = [
        frame
        async for frame in stream_events(record, registry, replay, ping_interval=0.02)
    ]
    assert frames[-1]["event"] == "response.completed"
