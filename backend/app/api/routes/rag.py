from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator.repository import TraceSpanRepository
from app.core.database import get_session
from app.core.llm import get_llm_client
from app.core.tracing import capture_latency_span, summarize_latency_spans
from app.documents.parser import DoclingDocumentParser
from app.rag.embeddings import EmbeddingService
from app.rag.indexer import RagIndexingService
from app.rag.models import (
    HybridRetrievalRequest,
    HybridRetrievalResponse,
    IndexDocumentRequest,
    IndexDocumentResponse,
)
from app.rag.repository import DocumentChunkRepository
from app.rag.retriever import HybridRetrievalService

router = APIRouter()


@router.post("/index", response_model=IndexDocumentResponse)
async def index_document(
    request: IndexDocumentRequest,
    session: AsyncSession = Depends(get_session),
) -> IndexDocumentResponse:
    trace_id = request.trace_id or str(uuid4())
    spans = []
    service = RagIndexingService(
        parser=DoclingDocumentParser(),
        embeddings=EmbeddingService(get_llm_client()),
        session=session,
    )
    async with capture_latency_span(
        spans,
        trace_id=trace_id,
        user_id=request.user_id,
        conversation_id=request.conversation_id,
        span_name="rag.index_document",
        span_type="rag",
        input_json={"file_id": request.file_id, "source_type": request.source_type},
    ) as span_output:
        response = await service.index_document(request)
        span_output["chunk_count"] = response.chunk_count
        span_output["embedding_count"] = response.embedding_count
    persisted = await _persist_trace_spans(session, spans)
    response.trace_id = trace_id
    response.latency_summary = summarize_latency_spans(trace_id, spans, persisted=persisted)
    return response


@router.post("/retrieve", response_model=HybridRetrievalResponse)
async def retrieve(
    request: HybridRetrievalRequest,
    session: AsyncSession = Depends(get_session),
) -> HybridRetrievalResponse:
    trace_id = request.trace_id or str(uuid4())
    spans = []
    service = HybridRetrievalService(
        repository=DocumentChunkRepository(session),
        embeddings=EmbeddingService(get_llm_client()),
    )
    async with capture_latency_span(
        spans,
        trace_id=trace_id,
        user_id=request.user_id,
        conversation_id=request.conversation_id,
        span_name="rag.retrieve",
        span_type="rag",
        input_json={"top_k": request.top_k, "file_ids": request.file_ids, "rerank": request.rerank},
    ) as span_output:
        response = await service.retrieve(request)
        span_output["candidate_count"] = len(response.candidates)
    persisted = await _persist_trace_spans(session, spans)
    response.trace_id = trace_id
    response.latency_summary = summarize_latency_spans(trace_id, spans, persisted=persisted)
    return response


async def _persist_trace_spans(session: AsyncSession, spans: list) -> bool:
    if not spans:
        return False
    try:
        await TraceSpanRepository(session).record_many(spans)
    except Exception:
        await session.rollback()
        return False
    return True
