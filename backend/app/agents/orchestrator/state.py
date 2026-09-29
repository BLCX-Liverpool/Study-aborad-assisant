from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.tracing import LatencySpan, LatencyTraceSummary, TraceEvent
from app.schemas.chat import AgentArtifact, ChatRequest, ChatTurn
from app.schemas.execution import MultiIntentExecutionPlan
from app.schemas.memory import MemoryContext
from app.schemas.router import RouterOutput


class AgentScopedState(BaseModel):
    agent_name: str
    run_count: int = 0
    last_run_id: str | None = None
    last_trace_id: str | None = None
    messages: list[ChatTurn] = Field(default_factory=list)
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    last_response: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def begin_run(self, *, run_id: str, trace_id: str, request: ChatRequest) -> None:
        self.run_count += 1
        self.last_run_id = run_id
        self.last_trace_id = trace_id
        self.messages.append(ChatTurn(role="user", content=request.message))

    def append_assistant_turn(self, response_text: str) -> None:
        if response_text:
            self.last_response = response_text
            self.messages.append(ChatTurn(role="assistant", content=response_text))


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
    agent_states: dict[str, AgentScopedState] = Field(default_factory=dict)
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

    def get_agent_state(self, agent_name: str) -> AgentScopedState:
        agent_state = self.agent_states.get(agent_name)
        if agent_state is None:
            agent_state = AgentScopedState(agent_name=agent_name)
            self.agent_states[agent_name] = agent_state
        return agent_state

    def prepare_for_request(self, request: ChatRequest) -> None:
        self.run_id = str(uuid4())
        self.persisted_agent_run_id = None
        self.trace_id = str(uuid4())
        self.router_output = None
        self.execution_plan = None
        self.worker_execution_results = []
        self.current_agent = None
        self.memory_context = None
        self.missing_information = []
        self.next_actions = []
        self.final_response = ""
        self.trace = []
        self.latency_spans = []
        self.latency_summary = None

        if not self.messages and request.history:
            self.messages.extend(request.history)
        self.messages.append(ChatTurn(role="user", content=request.message))

        for file_id in request.uploaded_file_ids:
            if file_id not in self.uploaded_file_ids:
                self.uploaded_file_ids.append(file_id)

    def append_assistant_turn(self) -> None:
        if self.final_response:
            self.messages.append(ChatTurn(role="assistant", content=self.final_response))
