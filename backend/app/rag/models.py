from pydantic import BaseModel, Field

from app.core.tracing import LatencyTraceSummary
from app.documents.models import DocumentChunkDraft


class IndexDocumentRequest(BaseModel):
    file_id: str
    user_id: str
    source_path: str
    source_name: str | None = None
    mime_type: str | None = None
    source_type: str = "indexed_document"
    rebuild: bool = True
    trace_id: str | None = None
    conversation_id: str | None = None


class IndexDocumentResponse(BaseModel):
    file_id: str
    chunk_count: int
    embedding_count: int
    status: str = "indexed"
    trace_id: str | None = None
    latency_summary: LatencyTraceSummary | None = None


class RetrievalCandidate(BaseModel):
    chunk_id: str
    file_id: str
    source_name: str | None = None
    content: str
    score: float
    retrieval_type: str
    page: int | None = None
    slide: int | None = None
    section: str | None = None
    section_path: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class HybridRetrievalRequest(BaseModel):
    user_id: str
    query: str
    file_ids: list[str] | None = None
    top_k: int = 8
    min_score: float = 0.0
    content_types: list[str] | None = None
    research_only: bool = False
    rerank: bool = True
    trace_id: str | None = None
    conversation_id: str | None = None


class HybridRetrievalResponse(BaseModel):
    query: str
    candidates: list[RetrievalCandidate]
    trace_id: str | None = None
    latency_summary: LatencyTraceSummary | None = None


class IndexedDocument(BaseModel):
    chunks: list[DocumentChunkDraft]
    embeddings: list[list[float]]
