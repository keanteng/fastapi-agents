# Legacy shim — the ORM models now live in app.agents.memory.models.
from app.agents.memory.models import Conversation, Message  # noqa: F401
