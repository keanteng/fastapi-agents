from __future__ import annotations

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

from app.features.tasks.orchestrator import run_limits, tasks_agent
from app.features.tasks.schemas import TaskStep


async def run_task(
    goal: str, max_steps: int
) -> tuple[str, list[TaskStep], dict[str, int]]:
    async with tasks_agent:
        result = await tasks_agent.run(goal, usage_limits=run_limits(max_steps))

    messages = result.all_messages()
    steps = _extract_steps(messages)

    usage = result.usage
    return (
        result.output,
        steps,
        {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "requests": usage.requests,
        },
    )


def _extract_steps(messages) -> list[TaskStep]:  # type: ignore[no-untyped-def]
    by_id: dict[str, ToolCallPart] = {}
    results: dict[str, str] = {}
    order: list[str] = []

    for msg in messages:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart) and part.tool_call_id:
                    by_id[part.tool_call_id] = part
                    order.append(part.tool_call_id)
        elif isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart) and part.tool_call_id:
                    results[part.tool_call_id] = str(part.content)[:2000]

    steps: list[TaskStep] = []
    for i, tid in enumerate(order, start=1):
        call = by_id[tid]
        steps.append(
            TaskStep(
                step=i,
                tool=call.tool_name,
                summary=_summarise_args(call.tool_name, call.args),
                result=results.get(tid, ""),
            )
        )
    return steps


def _summarise_args(tool_name: str, args) -> str:  # type: ignore[no-untyped-def]
    if isinstance(args, dict):
        for key in ("subtask", "input_text"):
            if key in args:
                return str(args[key])[:500]
    return str(args)[:500]
