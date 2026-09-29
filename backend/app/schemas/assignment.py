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


class AssignmentQuoteValidation(BaseModel):
    chunk_id: str
    status: Literal["passed", "failed"]
    quote: str | None = None
    reason: str | None = None
    start_char: int | None = None
    end_char: int | None = None


class AssignmentSourceQualityFinding(BaseModel):
    chunk_id: str
    source_name: str | None = None
    source_type: str | None = None
    score: float
    status: Literal["accepted", "rejected"]
    reasons: list[str] = Field(default_factory=list)


class AssignmentQACitation(BaseModel):
    evidence: EvidenceRef
    chunk_id: str
    retrieval_type: str
    score: float
    source_type: str | None = None


class AssignmentQARequest(BaseModel):
    user_id: str
    question: str
    file_ids: list[str] | None = None
    assignment: AssignmentAnalysis | None = None
    top_k: int = Field(default=8, ge=1, le=20)
    min_score: float = Field(default=0.15, ge=0.0, le=1.0)
    min_citations: int = Field(default=1, ge=1, le=5)
    include_research_sources: bool = True
    conversation_id: str | None = None
    trace_id: str | None = None


class AssignmentQAResponse(BaseModel):
    status: Literal["answered", "insufficient_evidence"]
    question: str
    answer: str
    citations: list[AssignmentQACitation] = Field(default_factory=list)
    quote_validations: list[AssignmentQuoteValidation] = Field(default_factory=list)
    source_quality: list[AssignmentSourceQualityFinding] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
