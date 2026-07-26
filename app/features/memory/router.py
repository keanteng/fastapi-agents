from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.features.memory.schemas import (
    AppendMessages,
    ConversationCreateResponse,
    MemoryAppendResponse,
    MemoryChatRequest,
    MemoryChatResponse,
    MemoryListResponse,
)
from app.features.memory.serialize import to_dto
from app.features.memory.service import (
    append_message,
    chat_with_memory,
    clear,
    create_conversation,
    list_messages,
)

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


@router.post("", response_model=ConversationCreateResponse)
async def create_memory(
    session: AsyncSession = Depends(get_session),
) -> ConversationCreateResponse:
    """Provision a conversation with a server-generated id (persisted)."""
    conversation_id = await create_conversation(session)
    return ConversationCreateResponse(conversation_id=conversation_id)


@router.get("/{conversation_id}", response_model=MemoryListResponse)
async def get_memory(
    conversation_id: str, session: AsyncSession = Depends(get_session)
) -> MemoryListResponse:
    messages = await list_messages(conversation_id, session)
    return MemoryListResponse(
        conversation_id=conversation_id, messages=to_dto(messages)
    )


@router.post("/{conversation_id}", response_model=MemoryAppendResponse)
async def append_memory(
    conversation_id: str,
    body: AppendMessages,
    session: AsyncSession = Depends(get_session),
) -> MemoryAppendResponse:
    before, after = await append_message(conversation_id, body.user_prompt, session)
    return MemoryAppendResponse(
        conversation_id=conversation_id, messages_before=before, messages_after=after
    )


@router.delete("/{conversation_id}")
async def delete_memory(
    conversation_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    cleared = await clear(conversation_id, session)
    if not cleared:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"conversation_id": conversation_id, "cleared": True}


@router.post("/{conversation_id}/chat", response_model=MemoryChatResponse)
async def memory_chat(
    conversation_id: str,
    body: MemoryChatRequest,
    session: AsyncSession = Depends(get_session),
) -> MemoryChatResponse:
    output, _messages, usage = await chat_with_memory(
        conversation_id, body.user_prompt, session, body.system_prompt_template
    )
    return MemoryChatResponse(
        conversation_id=conversation_id, output=output, usage=usage
    )
