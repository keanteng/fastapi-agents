from __future__ import annotations

from fastapi import APIRouter

from app.features.skills.registry import available_skills
from app.features.skills.schemas import SkillsRequest, SkillsResponse
from app.features.skills.service import orchestrate

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


@router.get("", response_model=dict[str, str])
async def list_skills() -> dict[str, str]:
    return available_skills()


@router.post("", response_model=SkillsResponse)
async def skills(req: SkillsRequest) -> SkillsResponse:
    output, usage = await orchestrate(req.user_prompt)
    return SkillsResponse(output=output, usage=usage)
