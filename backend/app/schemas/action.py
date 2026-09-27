from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import EvidenceRef

ActionItemType = Literal[
    "assignment_deadline",
    "bill_due",
    "tenancy_action",
    "travel_event",
    "appointment",
    "email_follow_up",
    "generic_task",
]

ActionItemStatus = Literal["draft", "confirmed", "dismissed"]


class ActionItem(BaseModel):
    title: str
    action_type: ActionItemType
    source_type: str
    source_id: str | None = None
    description: str | None = None
    deadline: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    location: str | None = None
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    status: ActionItemStatus = "draft"
    evidence: list[EvidenceRef] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class NoticeParseRequest(BaseModel):
    user_id: str
    text: str
    source_type: str = "notice"
    source_id: str | None = None
    source_name: str | None = None


class NoticeParseResponse(BaseModel):
    action_items: list[ActionItem] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
