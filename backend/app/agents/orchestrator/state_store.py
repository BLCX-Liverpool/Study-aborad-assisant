from __future__ import annotations

from threading import RLock
from uuid import uuid4

from app.agents.orchestrator.state import AgentState


class ConversationStateStore:
    """Conversation-scoped runtime state shared by workers across requests."""

    def __init__(self) -> None:
        self._states: dict[tuple[str, str], AgentState] = {}
        self._lock = RLock()

    def get_or_create(self, *, user_id: str, conversation_id: str | None) -> AgentState:
        resolved_conversation_id = conversation_id or str(uuid4())
        key = (user_id, resolved_conversation_id)
        with self._lock:
            state = self._states.get(key)
            if state is None:
                state = AgentState(user_id=user_id, conversation_id=resolved_conversation_id)
                self._states[key] = state
            return state

    def clear(self) -> None:
        with self._lock:
            self._states.clear()


default_conversation_state_store = ConversationStateStore()
