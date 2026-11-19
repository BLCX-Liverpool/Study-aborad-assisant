from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.chat import ChatRequest, ChatResponse


ExecutionMode = Literal["auto", "sync", "async"]
WorkflowStatusValue = Literal[
    "created",
    "planning",
    "running",
    "waiting_input",
    "completed",
    "partial_failed",
    "failed",
    "cancel_requested",
    "cancelled",
    "dead_lettered",
]
WorkflowStepStatusValue = Literal[
    "pending",
    "queued",
    "running",
    "completed",
    "needs_input",
    "retry_wait",
    "failed",
    "dead_lettered",
    "cancelled",
]


class ChatV2Request(ChatRequest):
    execution_mode: ExecutionMode = "auto"


class WorkflowAccepted(BaseModel):
    mode: Literal["async"] = "async"
    workflow_id: str
    trace_id: str
    status: WorkflowStatusValue
    status_url: str
    events_url: str


class SyncChatResult(BaseModel):
    mode: Literal["sync"] = "sync"
    response: ChatResponse


class WorkflowStepView(BaseModel):
    id: str
    step_key: str
    intent_name: str
    agent_intent: str
    status: WorkflowStepStatusValue
    attempt_count: int
    max_attempts: int
    result_summary: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    available_at: datetime | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None


class WorkflowArtifactView(BaseModel):
    id: str
    step_id: str
    name: str
    kind: str
    schema_version: int
    payload: dict[str, Any] | None = None
    storage_uri: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    created_at: datetime


class WorkflowView(BaseModel):
    id: str
    user_id: str
    conversation_id: str | None = None
    trace_id: str
    request_id: str
    workflow_type: str
    status: WorkflowStatusValue
    final_response: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    version: int
    progress: int = Field(default=0, ge=0, le=100)
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    steps: list[WorkflowStepView] = Field(default_factory=list)


class WorkflowInputSubmission(BaseModel):
    step_id: str
    agent_inputs: dict[str, dict[str, Any]]


class WorkflowActionResult(BaseModel):
    workflow_id: str
    status: WorkflowStatusValue
    changed: bool


class DeadLetterView(BaseModel):
    message_id: str
    workflow_id: str | None = None
    step_id: str | None = None
    status: str
    error: str | None = None
    received_at: datetime


class DeadLetterActionResult(BaseModel):
    original_message_id: str
    new_message_id: str | None = None
    status: str
