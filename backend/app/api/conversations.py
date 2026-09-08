from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.memory.repository import MemoryRepository
from app.agents.memory.schemas import MessageOut
from app.agents.memory.serialize import to_dto
from app.api.errors import AppError
from app.core.db import get_session

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


class ConversationSummary(BaseModel):
    conversation_id: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    preview: str | None = None


class ConversationDetail(BaseModel):
    conversation_id: str
    created_at: datetime
    messages: list[MessageOut] = Field(default_factory=list)


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ConversationSummary]:
    """List saved conversations, newest activity first."""
    summaries = await MemoryRepository(session).list_summaries()
    return [ConversationSummary(**summary) for summary in summaries]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationDetail:
    """Return a conversation transcript as stable message DTOs."""
    repo = MemoryRepository(session)
    found = await repo.get_conversation(conversation_id)
    if found is None:
        raise AppError(
            404,
            "conversation_not_found",
            f"conversation {conversation_id} does not exist",
        )
    created_at, messages = found
    return ConversationDetail(
        conversation_id=conversation_id,
        created_at=created_at,
        messages=to_dto(messages),
    )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Delete a conversation and its messages."""
    deleted = await MemoryRepository(session).clear(conversation_id)
    await session.commit()
    if not deleted:
        raise AppError(
            404,
            "conversation_not_found",
            f"conversation {conversation_id} does not exist",
        )
