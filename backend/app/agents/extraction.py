from __future__ import annotations

from app.agents.definitions import AgentDefinition

_EXTRACTOR_SCHEMA: dict[str, object] = {
    "title": "ExtractionResult",
    "type": "object",
    "description": "Structured output the agent must return.",
    "properties": {
        "entities": {
            "title": "Entities",
            "type": "array",
            "items": {"$ref": "#/$defs/Entity"},
        },
        "language": {
            "title": "Language",
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "default": None,
            "description": "Detected dominant language code (e.g. 'en').",
        },
        "summary": {
            "title": "Summary",
            "type": "string",
            "default": "",
            "description": "One-sentence summary of the input.",
        },
    },
    "$defs": {
        "Entity": {
            "title": "Entity",
            "type": "object",
            "properties": {
                "name": {
                    "title": "Name",
                    "type": "string",
                    "description": "The entity's surface form.",
                },
                "type": {
                    "title": "Type",
                    "type": "string",
                    "description": "PER, ORG, LOC, DATE, MISC.",
                },
                "confidence": {
                    "title": "Confidence",
                    "type": "number",
                    "default": 0.0,
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
            },
            "required": ["name", "type"],
        }
    },
}

# The former declarative ``extractor`` agent, kept in code as the sub-agent used
# by the ``extract_entities`` tool so it is no longer a selectable peer mode.
EXTRACTION_DEFINITION = AgentDefinition(
    name="extractor",
    description="Structured entity-extraction agent with no tools and no memory.",
    instructions="extractor",
    model=None,
    output_type="structured_output",
    output_schema=_EXTRACTOR_SCHEMA,
    capabilities=[],
    tools=[],
    uses_memory=False,
    default_max_steps=8,
)


async def extract_entities(text: str) -> str:
    """Extract named entities (PER/ORG/LOC/DATE/MISC), the dominant language and a
    one-sentence summary from ``text``, returning the result as JSON.

    Call this when the user asks to extract entities, people, organisations,
    places, dates or similar structured facts from text or an uploaded file.
    Read the file first with ``document_text`` and pass its text here.
    """
    from app.agents.build import build_agent

    agent = build_agent(EXTRACTION_DEFINITION, tools={})
    async with agent:
        result = await agent.run(text)
    output = result.output
    return output.model_dump_json()
