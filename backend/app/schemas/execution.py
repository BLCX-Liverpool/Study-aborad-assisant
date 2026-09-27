from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.planner import PlannerOutput, ReminderDraft
from app.schemas.router import StructuredIntent


ExecutionStepStatus = Literal["planned", "completed", "needs_input", "skipped", "blocked", "failed"]


class ExecutionStep(BaseModel):
    index: int
    intent_name: str
    agent_intent: str
    status: ExecutionStepStatus
    depends_on: list[int] = Field(default_factory=list)
    condition: str | None = None
    slots: dict = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    result_summary: str | None = None
    worker_intent: str | None = None
    artifact_count: int = 0
    tool_statuses: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)


class MultiIntentExecutionPlan(BaseModel):
    summary: str
    steps: list[ExecutionStep] = Field(default_factory=list)
    planner_output: PlannerOutput | None = None
    email_reminder_drafts: list[ReminderDraft] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unsupported_intents: list[str] = Field(default_factory=list)


class MultiIntentExecutionRequest(BaseModel):
    user_id: str
    message: str
    structured_intents: list[StructuredIntent] = Field(default_factory=list)
    agent_inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
