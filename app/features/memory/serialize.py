# Legacy shim — the serializer now lives in app.agents.memory.serialize.
from app.agents.memory.serialize import MessageOut, PartOut, to_dto  # noqa: F401
