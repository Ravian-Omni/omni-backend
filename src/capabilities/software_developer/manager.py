"""Software Developer capability, now a persona on the agent runtime.

Kept as a module so existing imports keep working; the class is a
``PersonaSession`` bound to the ``software_developer`` persona and exposes the
same methods the WebSocket router and the orchestrator call.
"""

from src.agent_runtime.session import PersonaManager, PersonaSession
from src.utilities.custom_manager import ChatContext

SoftwareDeveloperManager = PersonaManager


class SoftwareDeveloper(PersonaSession):
    """AI software developer running in the chat's workspace."""

    def __init__(self, context: ChatContext):
        super().__init__(context, "software_developer")


__all__ = ["SoftwareDeveloper", "SoftwareDeveloperManager"]
