from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.assignment import AssignmentAnalysis
from app.schemas.common import EvidenceRef

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


class ResearchSourceIndexRequest(BaseModel):
    user_id: str
    file_id: str
    source_path: Path
    source_name: str | None = None
    mime_type: str | None = "application/pdf"


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
