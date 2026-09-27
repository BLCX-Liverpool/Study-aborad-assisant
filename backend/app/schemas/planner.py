from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.action import ActionItem
from app.schemas.common import PlannedEvent, PlannedTask
from app.schemas.assignment import AssignmentAnalysis
from app.schemas.email import EmailProviderName, EmailSendResult


class ReminderDraft(BaseModel):
    title: str
    remind_at: datetime
    channel: str = "in_app"
    task_title: str | None = None
    event_title: str | None = None


class ScheduleBlock(BaseModel):
    title: str
    start_time: datetime
    end_time: datetime
    source_type: str | None = None
    source_id: str | None = None


class ConflictFinding(BaseModel):
    message: str
    planned_title: str
    existing_title: str
    planned_start: datetime
    planned_end: datetime
    existing_start: datetime
    existing_end: datetime


class AssignmentPlanningRequest(BaseModel):
    user_id: str
    assignment: AssignmentAnalysis
    source_id: str | None = None
    existing_blocks: list[ScheduleBlock] = Field(default_factory=list)


class GlobalPlanningRequest(BaseModel):
    user_id: str
    items: list[ActionItem] = Field(default_factory=list)
    planning_horizon_days: int = Field(default=30, ge=1, le=180)
    existing_blocks: list[ScheduleBlock] = Field(default_factory=list)
    memory_preferences: list[str] = Field(default_factory=list)


class PlannerOutput(BaseModel):
    tasks: list[PlannedTask] = Field(default_factory=list)
    events: list[PlannedEvent] = Field(default_factory=list)
    reminders: list[ReminderDraft] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class SavedPlannerOutput(BaseModel):
    task_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    reminder_ids: list[str] = Field(default_factory=list)


class DueReminder(BaseModel):
    id: str
    user_id: str
    title: str
    channel: str
    remind_at: datetime
    task_id: str | None = None
    event_id: str | None = None


class EmailReminderQueueItem(BaseModel):
    reminder_id: str
    user_id: str
    to_email: str | None = None
    subject: str
    body: str
    remind_at: datetime
    status: str = "queued"


class EmailReminderSendRequest(BaseModel):
    user_id: str
    provider: EmailProviderName = "dry_run"
    to_email: str
    approved: bool = False
    reminder_ids: list[str] = Field(default_factory=list)
    idempotency_prefix: str | None = None


class EmailReminderSendResponse(BaseModel):
    sent: list[EmailSendResult] = Field(default_factory=list)
    skipped: list[EmailSendResult] = Field(default_factory=list)
    marked_sent_count: int = 0
