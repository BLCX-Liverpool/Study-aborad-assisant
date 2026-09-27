from app.rag.models import RetrievalCandidate
from app.rag.retriever import filter_candidates, merge_candidates, rerank_candidates


def test_merge_candidates_marks_duplicates_as_hybrid() -> None:
    bm25 = [
        RetrievalCandidate(
            chunk_id="chunk_1",
            file_id="file_1",
            content="deadline is 10 october",
            score=4.0,
            retrieval_type="bm25",
        )
    ]
    vector = [
        RetrievalCandidate(
            chunk_id="chunk_1",
            file_id="file_1",
            content="deadline is 10 october",
            score=0.8,
            retrieval_type="vector",
        )
    ]

    merged = merge_candidates(bm25, vector, top_k=5)
    assert len(merged) == 1
    assert merged[0].retrieval_type == "hybrid"
    assert merged[0].score == 1.0


def test_filter_candidates_supports_research_threshold_and_content_types() -> None:
    candidates = [
        RetrievalCandidate(
            chunk_id="research_pdf",
            file_id="file_1",
            content="paper summary",
            score=0.88,
            retrieval_type="hybrid",
            metadata={"source_type": "research_source", "content_type": "application/pdf"},
        ),
        RetrievalCandidate(
            chunk_id="coursework",
            file_id="file_2",
            content="assignment brief",
            score=0.95,
            retrieval_type="bm25",
            metadata={"source_type": "uploaded_document", "content_type": "application/pdf"},
        ),
        RetrievalCandidate(
            chunk_id="low_score",
            file_id="file_3",
            content="weak source",
            score=0.12,
            retrieval_type="vector",
            metadata={"source_type": "research_source", "content_type": "text/html"},
        ),
    ]

    filtered = filter_candidates(
        candidates,
        min_score=0.5,
        content_types=["application/pdf"],
        research_only=True,
    )

    assert [candidate.chunk_id for candidate in filtered] == ["research_pdf"]


def test_rerank_candidates_boosts_query_term_overlap() -> None:
    candidates = [
        RetrievalCandidate(
            chunk_id="generic",
            file_id="file_1",
            content="student assistant",
            score=0.7,
            retrieval_type="bm25",
        ),
        RetrievalCandidate(
            chunk_id="specific",
            file_id="file_2",
            content="student assistant rag evaluation",
            score=0.7,
            retrieval_type="bm25",
        ),
    ]

    reranked = rerank_candidates("rag evaluation", candidates)

    assert reranked[0].chunk_id == "specific"
