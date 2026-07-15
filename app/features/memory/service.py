"""Memory service: bridge the repository to the memory-aware agent.

Stateless functions take the caller's ``AsyncSession`` so transactions are
owned by the route (and committed here once mutations are complete). The
agent still uses pydantic-ai's ``message_history`` for replay; the
repository only (de)serialises raw ``ModelMessage`` rows.
"""

from __future__ import annotations

import uuid

from datetime import datetime, timezone

from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.prompts import render
from app.features.memory.agent import memory_agent
from app.features.memory.repository import MemoryRepository

_SYSTEM_TEMPLATE = "features/memory/templates/system.jinja"


def _user_message(user_prompt: str) -> ModelRequest:
    return ModelRequest(
        parts=[UserPromptPart(content=user_prompt, timestamp=datetime.now(timezone.utc))]
    )


def _repo(session: AsyncSession) -> MemoryRepository:
    return MemoryRepository(session)


async def create_conversation(session: AsyncSession) -> str:
    """Provision a new conversation row and return its server-generated id."""
    conversation_id = uuid.uuid4().hex
    repo = _repo(session)
    await repo.ensure(conversation_id)
    await session.commit()
    return conversation_id


async def list_messages(
    conversation_id: str, session: AsyncSession
) -> list[ModelMessage]:
    return await _repo(session).get(conversation_id)


async def append_message(
    conversation_id: str, user_prompt: str, session: AsyncSession
) -> tuple[int, int]:
    repo = _repo(session)
    if not await repo.exists(conversation_id):
        await repo.ensure(conversation_id)
    before = await repo.count(conversation_id)
    await repo.append(conversation_id, [_user_message(user_prompt)])
    after = await repo.count(conversation_id)
    await session.commit()
    return before, after


async def clear(conversation_id: str, session: AsyncSession) -> bool:
    cleared = await _repo(session).clear(conversation_id)
    await session.commit()
    return cleared


async def chat_with_memory(
    conversation_id: str,
    user_prompt: str,
    session: AsyncSession,
    system_prompt_template: str | None = None,
) -> tuple[str, list[ModelMessage], dict[str, int]]:
    """Run the memory agent, replaying stored history and persisting new turns."""
    repo = _repo(session)
    if not await repo.exists(conversation_id):
        await repo.ensure(conversation_id)

    history = await repo.get(conversation_id)

    template = system_prompt_template or _SYSTEM_TEMPLATE
    instructions = render(template, conversation_id=conversation_id)

    async with memory_agent:
        result = await memory_agent.run(
            user_prompt,
            message_history=history,
            instructions=instructions,
        )
    usage = result.usage
    await repo.set(conversation_id, result.all_messages())
    await session.commit()
    return result.output, result.all_messages(), {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "requests": usage.requests,
    }