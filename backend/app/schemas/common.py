from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EvidenceRef(BaseModel):
    source_file_id: str | None = None
    source_name: str | None = None
    page: int | None = None
    slide: int | None = None
    section: str | None = None
    quote: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PlannedTask(BaseModel):
    title: str
    description: str | None = None
    source_type: str
    source_id: str | None = None
    start_time: datetime | None = None
    deadline: datetime | None = None
    estimated_minutes: int | None = None
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    status: Literal["todo", "in_progress", "done", "cancelled"] = "todo"
    evidence: list[EvidenceRef] = Field(default_factory=list)


class PlannedEvent(BaseModel):
    title: str
    description: str | None = None
    location: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    source_type: str | None = None
    source_id: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
