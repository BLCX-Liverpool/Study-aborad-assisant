from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.tracing import LatencyTraceSummary, TraceEvent
from app.schemas.router import RouterOutput


ChatRole = Literal["user", "assistant", "system"]


class ChatTurn(BaseModel):
    role: ChatRole
    content: str


class ChatRequest(BaseModel):
    user_id: str
    message: str
    conversation_id: str | None = None
    history: list[ChatTurn] = Field(default_factory=list)
    uploaded_file_ids: list[str] = Field(default_factory=list)
    agent_inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    persist_agent_runs: bool = False


class AgentArtifact(BaseModel):
    name: str
    kind: str
    payload: dict[str, Any]


class ChatResponse(BaseModel):
    user_id: str
    conversation_id: str
    trace_id: str
    router: RouterOutput
    final_response: str
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)
    latency_summary: LatencyTraceSummary | None = None
    memory_context: dict[str, Any] | None = None
    missing_information: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
