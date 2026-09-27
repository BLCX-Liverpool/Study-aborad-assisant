from app.core.tracing import capture_current_latency_span
from app.rag.embeddings import EmbeddingService
from app.rag.models import HybridRetrievalRequest, HybridRetrievalResponse, RetrievalCandidate
from app.rag.repository import DocumentChunkRepository


class HybridRetrievalService:
    def __init__(
        self,
        repository: DocumentChunkRepository,
        embeddings: EmbeddingService,
    ) -> None:
        self.repository = repository
        self.embeddings = embeddings

    async def retrieve(self, request: HybridRetrievalRequest) -> HybridRetrievalResponse:
        async with capture_current_latency_span(
            span_name="rag.retrieve_bm25",
            span_type="rag",
            input_json={"top_k": request.top_k, "file_ids": request.file_ids},
        ) as span_output:
            bm25_candidates = await self.repository.bm25_search(
                user_id=request.user_id,
                query=request.query,
                file_ids=request.file_ids,
                top_k=request.top_k,
            )
            span_output["candidate_count"] = len(bm25_candidates)
        async with capture_current_latency_span(
            span_name="rag.embedding_query",
            span_type="rag",
            input_json={"query_length": len(request.query)},
        ):
            query_embedding = (await self.embeddings.embed_texts([request.query]))[0]
        async with capture_current_latency_span(
            span_name="rag.retrieve_vector",
            span_type="rag",
            input_json={"top_k": request.top_k, "file_ids": request.file_ids},
        ) as span_output:
            vector_candidates = await self.repository.vector_search(
                user_id=request.user_id,
                query_embedding=query_embedding,
                file_ids=request.file_ids,
                top_k=request.top_k,
            )
            span_output["candidate_count"] = len(vector_candidates)
        async with capture_current_latency_span(
            span_name="rag.merge_filter_rerank",
            span_type="rag",
            input_json={
                "bm25_count": len(bm25_candidates),
                "vector_count": len(vector_candidates),
                "rerank": request.rerank,
            },
        ) as span_output:
            merged = merge_candidates(bm25_candidates, vector_candidates, request.top_k * 2)
            filtered = filter_candidates(
                merged,
                min_score=request.min_score,
                content_types=request.content_types,
                research_only=request.research_only,
            )
            reranked = rerank_candidates(request.query, filtered) if request.rerank else filtered
            span_output["merged_count"] = len(merged)
            span_output["filtered_count"] = len(filtered)
        merged = reranked[: request.top_k]
        return HybridRetrievalResponse(query=request.query, candidates=merged)


def merge_candidates(
    bm25_candidates: list[RetrievalCandidate],
    vector_candidates: list[RetrievalCandidate],
    top_k: int,
) -> list[RetrievalCandidate]:
    merged: dict[str, RetrievalCandidate] = {}

    for candidate in normalize_scores(bm25_candidates):
        merged[candidate.chunk_id] = candidate

    for candidate in normalize_scores(vector_candidates):
        existing = merged.get(candidate.chunk_id)
        if existing is None:
            merged[candidate.chunk_id] = candidate
            continue
        existing.score = max(existing.score, candidate.score)
        existing.retrieval_type = "hybrid"

    return sorted(merged.values(), key=lambda item: item.score, reverse=True)[:top_k]


def normalize_scores(candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
    if not candidates:
        return []
    max_score = max(candidate.score for candidate in candidates) or 1.0
    normalized: list[RetrievalCandidate] = []
    for candidate in candidates:
        copied = candidate.model_copy()
        copied.score = copied.score / max_score
        normalized.append(copied)
    return normalized


def filter_candidates(
    candidates: list[RetrievalCandidate],
    *,
    min_score: float,
    content_types: list[str] | None,
    research_only: bool,
) -> list[RetrievalCandidate]:
    filtered = []
    for candidate in candidates:
        if candidate.score < min_score:
            continue
        if content_types and candidate.metadata.get("content_type") not in content_types:
            continue
        if research_only and candidate.metadata.get("source_type") not in {
            "research",
            "research_source",
            "paper_pdf",
            "arxiv",
            "web",
        }:
            continue
        filtered.append(candidate)
    return filtered


def rerank_candidates(query: str, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
    query_terms = {term.lower() for term in query.split() if len(term) >= 3}
    reranked = []
    for candidate in candidates:
        content_terms = {term.lower() for term in candidate.content.split() if len(term) >= 3}
        overlap = len(query_terms & content_terms) / max(len(query_terms), 1)
        boosted = candidate.model_copy()
        boosted.score = round(0.75 * boosted.score + 0.25 * overlap, 6)
        reranked.append(boosted)
    return sorted(reranked, key=lambda item: item.score, reverse=True)
