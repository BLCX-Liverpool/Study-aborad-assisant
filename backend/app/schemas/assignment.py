from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import EvidenceRef, PlannedTask


class AssignmentRequirement(BaseModel):
    requirement_type: Literal[
        "objective",
        "deliverable",
        "deadline",
        "word_limit",
        "format",
        "marking_criteria",
        "constraint",
        "submission",
        "other",
    ]
    content: str
    evidence: list[EvidenceRef] = Field(default_factory=list)


class AssignmentAnalysis(BaseModel):
    course_code: str | None = None
    title: str | None = None
    objective: str
    deliverables: list[str] = Field(default_factory=list)
    deadline: datetime | None = None
    marking_criteria: list[AssignmentRequirement] = Field(default_factory=list)
    constraints: list[AssignmentRequirement] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    possible_ideas: list[str] = Field(default_factory=list)
    suggested_structure: list[str] = Field(default_factory=list)
    research_queries: list[str] = Field(default_factory=list)
    research_sources: list[EvidenceRef] = Field(default_factory=list)
    action_plan: list[PlannedTask] = Field(default_factory=list)

