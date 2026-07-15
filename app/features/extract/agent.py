"""Extraction agent producing structured ``ExtractionResult`` output."""

from __future__ import annotations

from pydantic_ai import Agent

from app.core.model import get_model
from app.core.prompts import render
from app.features.extract.schemas import ExtractionResult

extract_agent: Agent[None, ExtractionResult] = Agent(
    get_model(),
    instructions=lambda _: render("features/extract/templates/system.jinja"),
    output_type=ExtractionResult,
)