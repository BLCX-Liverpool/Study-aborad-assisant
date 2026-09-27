from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.tracing import LatencySpan, LatencyTraceSummary, TraceEvent
from app.schemas.chat import AgentArtifact, ChatTurn
from app.schemas.execution import MultiIntentExecutionPlan
from app.schemas.memory import MemoryContext
from app.schemas.router import RouterOutput


class AgentState(BaseModel):
    user_id: str
    conversation_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    persisted_agent_run_id: str | None = None
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    messages: list[ChatTurn] = Field(default_factory=list)
    uploaded_file_ids: list[str] = Field(default_factory=list)
    router_output: RouterOutput | None = None
    execution_plan: MultiIntentExecutionPlan | None = None
    worker_execution_results: list[dict[str, Any]] = Field(default_factory=list)
    current_agent: str | None = None
    memory_context: MemoryContext | None = None
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    final_response: str = ""
    trace: list[TraceEvent] = Field(default_factory=list)
    latency_spans: list[LatencySpan] = Field(default_factory=list)
    latency_summary: LatencyTraceSummary | None = None

    def add_trace(self, name: str, payload: dict[str, Any] | None = None) -> None:
        self.trace.append(
            TraceEvent(
                trace_id=self.trace_id,
                name=name,
                payload=payload or {},
            )
        )

    def add_artifact(self, name: str, kind: str, payload: dict[str, Any]) -> None:
        self.artifacts.append(AgentArtifact(name=name, kind=kind, payload=payload))
