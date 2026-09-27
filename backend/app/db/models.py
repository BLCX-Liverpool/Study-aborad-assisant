from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def uuid_str() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ReminderStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    CANCELLED = "cancelled"
    FAILED = "failed"


class PermissionRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class EmailSendStatus(StrEnum):
    REQUIRES_APPROVAL = "requires_approval"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    home_country: Mapped[str | None] = mapped_column(String(128), nullable=True)
    study_country: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    topic_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_entities_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")

    messages: Mapped[list["ConversationMessage"]] = relationship(back_populates="conversation")


class ConversationMessage(Base, TimestampMixin):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class StoredFile(Base, TimestampMixin):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_path: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(128), default="uploaded_document")
    checksum: Mapped[str] = mapped_column(String(128), index=True)

    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="file")


class DocumentChunk(Base, TimestampMixin):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slide: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String(512), nullable=True)
    section_path: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    heading_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parse_strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_area_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    file: Mapped[StoredFile] = relationship(back_populates="chunks")


class Memory(Base, TimestampMixin):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    namespace: Mapped[str] = mapped_column(String(64), index=True)
    memory_type: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    access_policy_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    priority: Mapped[str] = mapped_column(String(32), default="medium")
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.TODO)
    created_by_agent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)


class Event(Base, TimestampMixin):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="scheduled")
    evidence_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)


class Reminder(Base, TimestampMixin):
    __tablename__ = "reminders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"), nullable=True, index=True)
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    channel: Mapped[str] = mapped_column(String(64), default="in_app")
    status: Mapped[ReminderStatus] = mapped_column(Enum(ReminderStatus), default=ReminderStatus.PENDING)


class EmailSendAttempt(Base, TimestampMixin):
    __tablename__ = "email_send_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    to_email: Mapped[str] = mapped_column(String(255))
    from_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(512))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[EmailSendStatus] = mapped_column(Enum(EmailSendStatus), default=EmailSendStatus.REQUIRES_APPROVAL)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    source_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_name: Mapped[str] = mapped_column(String(128), index=True)
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.QUEUED)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    tool_runs: Mapped[list["ToolRun"]] = relationship(back_populates="agent_run")


class RouterObservation(Base, TimestampMixin):
    __tablename__ = "router_observations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    primary_intent: Mapped[str] = mapped_column(String(128), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    structured_intents_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    fusion_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    clarification_questions_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class TraceSpan(Base, TimestampMixin):
    __tablename__ = "trace_spans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True, index=True)
    span_name: Mapped[str] = mapped_column(String(128), index=True)
    span_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float] = mapped_column(Float)
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ToolRun(Base, TimestampMixin):
    __tablename__ = "tool_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    permission_level: Mapped[str] = mapped_column(String(64))
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.QUEUED)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    agent_run: Mapped[AgentRun] = relationship(back_populates="tool_runs")


class MemoryAccessLog(Base, TimestampMixin):
    __tablename__ = "memory_access_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id"), index=True)
    access_type: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class RagRetrievalLog(Base, TimestampMixin):
    __tablename__ = "rag_retrieval_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True, index=True)
    query: Mapped[str] = mapped_column(Text)
    retrieval_type: Mapped[str] = mapped_column(String(64))
    results_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)


class PermissionRequest(Base, TimestampMixin):
    __tablename__ = "permission_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True, index=True)
    permission_level: Mapped[str] = mapped_column(String(64))
    action_name: Mapped[str] = mapped_column(String(128))
    request_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[PermissionRequestStatus] = mapped_column(
        Enum(PermissionRequestStatus),
        default=PermissionRequestStatus.PENDING,
    )


class VerifierResult(Base, TimestampMixin):
    __tablename__ = "verifier_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid_str)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True, index=True)
    verifier_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
