from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.assignment import AssignmentAnalysis, AssignmentQAResponse
from app.schemas.common import EvidenceRef
from app.rag.models import IndexDocumentResponse

ResearchSourceType = Literal["arxiv", "web", "paper_pdf"]


class ResearchSource(BaseModel):
    source_type: ResearchSourceType
    title: str
    url: str
    summary: str | None = None
    authors: list[str] = Field(default_factory=list)
    published_at: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class ResearchQueryRequest(BaseModel):
    assignment: AssignmentAnalysis
    max_queries: int = Field(default=5, ge=1, le=10)


class ResearchQueryResponse(BaseModel):
    queries: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ArxivSearchRequest(BaseModel):
    query: str
    max_results: int = Field(default=5, ge=1, le=20)


class ArxivSearchResponse(BaseModel):
    query: str
    sources: list[ResearchSource] = Field(default_factory=list)


class WebSearchRequest(BaseModel):
    query: str
    max_results: int = Field(default=5, ge=1, le=10)


class WebSearchResponse(BaseModel):
    query: str
    sources: list[ResearchSource] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class PaperDownloadRequest(BaseModel):
    url: str
    output_dir: Path
    filename: str | None = None


class PaperDownloadResponse(BaseModel):
    url: str
    local_path: Path
    content_type: str | None = None
    bytes_written: int
    sha256: str | None = None
    duplicate_of: Path | None = None
    title: str | None = None
    summary: str | None = None
    metadata: dict = Field(default_factory=dict)


class ResearchWorkflowRequest(BaseModel):
    user_id: str
    assignment: AssignmentAnalysis
    include_web: bool = True
    include_arxiv: bool = True
    max_results_per_query: int = Field(default=3, ge=1, le=10)


class ResearchWorkflowResponse(BaseModel):
    queries: list[str] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ResearchSynthesisSource(BaseModel):
    title: str
    url: str | None = None
    source_type: str | None = None
    summary: str | None = None
    evidence_count: int = 0


class ResearchSynthesisReport(BaseModel):
    status: Literal["supported", "partial", "insufficient_evidence"]
    key_findings: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    selected_sources: list[ResearchSynthesisSource] = Field(default_factory=list)
    writing_guidance: list[str] = Field(default_factory=list)


class AssignmentResearchEvidenceReviewRequest(BaseModel):
    user_id: str
    assignment: AssignmentAnalysis
    indexed_file_ids: list[str] | None = None
    research_sources: list[ResearchSource] = Field(default_factory=list)
    ideas: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    max_questions: int = Field(default=5, ge=1, le=10)
    min_score: float = Field(default=0.15, ge=0.0, le=1.0)
    conversation_id: str | None = None
    trace_id: str | None = None


class AssignmentResearchEvidenceReviewResponse(BaseModel):
    queries: list[str] = Field(default_factory=list)
    qa_results: list[AssignmentQAResponse] = Field(default_factory=list)
    idea_verification: IdeaVerificationResponse | None = None
    synthesis: ResearchSynthesisReport
    assumptions: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class ResearchSourceIndexRequest(BaseModel):
    user_id: str
    file_id: str
    source_path: Path
    source_name: str | None = None
    mime_type: str | None = "application/pdf"


class SelectedResearchSourceIndexRequest(BaseModel):
    user_id: str
    sources: list[ResearchSource] = Field(default_factory=list)
    conversation_id: str | None = None
    trace_id: str | None = None


class SelectedResearchSourceIndexResult(BaseModel):
    source: ResearchSource
    file_id: str
    local_path: Path | None = None
    download: PaperDownloadResponse | None = None
    index: IndexDocumentResponse | None = None
    status: Literal["indexed", "download_failed", "index_failed", "skipped"] = "indexed"
    error: str | None = None


class SelectedResearchSourceIndexResponse(BaseModel):
    user_id: str
    indexed_file_ids: list[str] = Field(default_factory=list)
    results: list[SelectedResearchSourceIndexResult] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class IdeaVerificationRequest(BaseModel):
    assignment: AssignmentAnalysis
    ideas: list[str] = Field(default_factory=list)
    research_sources: list[ResearchSource] = Field(default_factory=list)


class IdeaVerificationFinding(BaseModel):
    idea: str
    status: Literal["supported", "needs_more_evidence", "conflicts_with_constraints"]
    reasons: list[str] = Field(default_factory=list)
    supporting_sources: list[str] = Field(default_factory=list)


class IdeaVerificationResponse(BaseModel):
    findings: list[IdeaVerificationFinding] = Field(default_factory=list)
    recommended_ideas: list[str] = Field(default_factory=list)
