from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


CURRENT_MESSAGE_SCHEMA_VERSION = 2
# Producers emit v2 while consumers continue accepting the immediately previous
# version during rolling deployments.
SUPPORTED_MESSAGE_SCHEMA_VERSIONS = {1, 2}


def utc_now() -> datetime:
    return datetime.now(UTC)


class MessageEnvelope(BaseModel):
    schema_version: int = CURRENT_MESSAGE_SCHEMA_VERSION
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    message_type: str
    workflow_id: str
    trace_id: str
    parent_span_id: str | None = None
    causation_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: int) -> int:
        if value not in SUPPORTED_MESSAGE_SCHEMA_VERSIONS:
            raise ValueError(f"Unsupported message schema version: {value}")
        return value


class WorkflowPrepareCommand(MessageEnvelope):
    message_type: Literal["workflow.prepare"] = "workflow.prepare"
    input_ref: str


class AgentTaskCommand(MessageEnvelope):
    message_type: Literal["agent.task.requested"] = "agent.task.requested"
    step_id: str
    agent: str
    input_ref: str
    dependency_artifact_ids: list[str] = Field(default_factory=list)
    attempt: int = Field(default=1, ge=1)


AgentStepEventType = Literal[
    "agent.step.started",
    "agent.step.completed",
    "agent.step.needs_input",
    "agent.step.retry_scheduled",
    "agent.step.failed",
    "agent.step.dead_lettered",
    "agent.step.cancelled",
]


class AgentStepEvent(MessageEnvelope):
    message_type: AgentStepEventType
    step_id: str
    agent: str
    artifact_ids: list[str] = Field(default_factory=list)
    attempt: int = Field(default=1, ge=1)
    result_summary: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    completed_at: datetime | None = None
    worker_instance_id: str | None = None


class WorkflowCompletedEvent(MessageEnvelope):
    message_type: Literal["workflow.completed"] = "workflow.completed"
    artifact_ids: list[str] = Field(default_factory=list)
    completed_at: datetime = Field(default_factory=utc_now)


class ArtifactCreatedEvent(MessageEnvelope):
    message_type: Literal["artifact.created"] = "artifact.created"
    step_id: str
    artifact_id: str
    artifact_kind: str


def encoded_message_size(message: BaseModel) -> int:
    return len(
        json.dumps(message.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
