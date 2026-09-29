import re

from app.rag.models import HybridRetrievalRequest, RetrievalCandidate
from app.rag.retriever import HybridRetrievalService
from app.schemas.assignment import (
    AssignmentQACitation,
    AssignmentQARequest,
    AssignmentQAResponse,
    AssignmentQuoteValidation,
    AssignmentSourceQualityFinding,
)
from app.schemas.common import EvidenceRef


ACADEMIC_SOURCE_TYPES = {
    "indexed_document",
    "uploaded_document",
    "assignment_brief",
    "research",
    "research_source",
    "paper_pdf",
    "arxiv",
    "web",
}


class AssignmentQAService:
    def __init__(self, retriever: HybridRetrievalService) -> None:
        self.retriever = retriever

    async def answer(self, request: AssignmentQARequest) -> AssignmentQAResponse:
        retrieval = await self.retriever.retrieve(
            HybridRetrievalRequest(
                user_id=request.user_id,
                query=_assignment_augmented_query(request),
                file_ids=request.file_ids,
                top_k=request.top_k,
                min_score=0.0,
                rerank=True,
                trace_id=request.trace_id,
                conversation_id=request.conversation_id,
            )
        )

        source_quality: list[AssignmentSourceQualityFinding] = []
        validations: list[AssignmentQuoteValidation] = []
        citations: list[AssignmentQACitation] = []

        for candidate in retrieval.candidates:
            quality = assess_source_quality(
                candidate,
                min_score=request.min_score,
                include_research_sources=request.include_research_sources,
            )
            source_quality.append(quality)
            if quality.status == "rejected":
                validations.append(
                    AssignmentQuoteValidation(
                        chunk_id=candidate.chunk_id,
                        status="failed",
                        reason="Source quality gate rejected this chunk before quote validation.",
                    )
                )
                continue

            validation = validate_exact_quote(request.question, candidate)
            validations.append(validation)
            if validation.status == "failed" or not validation.quote:
                continue

            citations.append(
                AssignmentQACitation(
                    evidence=EvidenceRef(
                        source_file_id=candidate.file_id,
                        source_name=candidate.source_name,
                        page=candidate.page,
                        slide=candidate.slide,
                        section=candidate.section,
                        quote=validation.quote,
                        start_char=validation.start_char,
                        end_char=validation.end_char,
                        confidence=_citation_confidence(candidate.score, validation.quote),
                    ),
                    chunk_id=candidate.chunk_id,
                    retrieval_type=candidate.retrieval_type,
                    score=candidate.score,
                    source_type=_source_type(candidate),
                )
            )

        citations = citations[: request.top_k]
        if len(citations) < request.min_citations:
            return AssignmentQAResponse(
                status="insufficient_evidence",
                question=request.question,
                answer=(
                    "证据不足，无法基于已上传的作业材料或已索引研究资料可靠回答。"
                    "请补充 assignment brief、rubric、lecture notes 或已选研究来源后再提问。"
                ),
                citations=citations,
                quote_validations=validations,
                source_quality=source_quality,
                assumptions=[
                    "QA only answers when at least the requested number of citations pass source quality and exact quote validation.",
                    "Rejected or low-scoring chunks are not used as evidence.",
                ],
                next_actions=[
                    "Upload or index the assignment brief and marking rubric.",
                    "Index selected research sources with /api/assignment/research/index-source.",
                    "Ask a narrower question tied to one requirement, criterion, or source.",
                ],
                confidence=_overall_confidence(citations),
            )

        return AssignmentQAResponse(
            status="answered",
            question=request.question,
            answer=synthesize_grounded_answer(request.question, citations),
            citations=citations,
            quote_validations=validations,
            source_quality=source_quality,
            assumptions=[
                "Answer is synthesized only from citations that passed exact quote validation.",
                "Citation order follows retrieval relevance after reranking.",
            ],
            next_actions=[
                "Use the cited chunk ids to inspect the source evidence before drafting final coursework text.",
            ],
            confidence=_overall_confidence(citations),
        )


def assess_source_quality(
    candidate: RetrievalCandidate,
    *,
    min_score: float,
    include_research_sources: bool,
) -> AssignmentSourceQualityFinding:
    reasons: list[str] = []
    source_type = _source_type(candidate)

    if candidate.score < min_score:
        reasons.append(f"Retrieval score {candidate.score:.3f} is below min_score {min_score:.3f}.")
    if not candidate.content.strip():
        reasons.append("Chunk content is empty.")
    if len(candidate.content.strip()) < 40:
        reasons.append("Chunk content is too short to support a grounded answer.")
    if source_type not in ACADEMIC_SOURCE_TYPES:
        reasons.append(f"Unsupported source_type: {source_type or 'missing'}.")
    if not include_research_sources and source_type in {"research", "research_source", "paper_pdf", "arxiv", "web"}:
        reasons.append("Research sources were excluded for this question.")

    return AssignmentSourceQualityFinding(
        chunk_id=candidate.chunk_id,
        source_name=candidate.source_name,
        source_type=source_type,
        score=candidate.score,
        status="rejected" if reasons else "accepted",
        reasons=reasons,
    )


def validate_exact_quote(question: str, candidate: RetrievalCandidate) -> AssignmentQuoteValidation:
    quote = select_evidence_quote(question, candidate.content)
    if not quote:
        return AssignmentQuoteValidation(
            chunk_id=candidate.chunk_id,
            status="failed",
            reason="No sentence or passage in the chunk overlapped enough with the question.",
        )

    start = candidate.content.find(quote)
    if start < 0:
        return AssignmentQuoteValidation(
            chunk_id=candidate.chunk_id,
            status="failed",
            quote=quote,
            reason="Selected quote was not an exact substring of the source chunk.",
        )

    return AssignmentQuoteValidation(
        chunk_id=candidate.chunk_id,
        status="passed",
        quote=quote,
        start_char=start,
        end_char=start + len(quote),
    )


def select_evidence_quote(question: str, content: str) -> str | None:
    question_terms = _terms(question)
    if not question_terms:
        return None
    best_sentence = None
    best_score = 0.0
    for sentence in _sentences(content):
        sentence_terms = _terms(sentence)
        if not sentence_terms:
            continue
        overlap = len(question_terms & sentence_terms) / max(len(question_terms), 1)
        if overlap > best_score:
            best_score = overlap
            best_sentence = sentence
    if best_sentence and best_score >= 0.18:
        return _truncate_quote(best_sentence)

    compact = " ".join(content.split())
    if len(compact) >= 80:
        return _truncate_quote(compact)
    return None


def synthesize_grounded_answer(question: str, citations: list[AssignmentQACitation]) -> str:
    evidence_lines = []
    for index, citation in enumerate(citations[:4], start=1):
        quote = citation.evidence.quote or ""
        location = _citation_location(citation.evidence)
        evidence_lines.append(f"{index}. {quote} ({location})")

    return (
        f"基于已验证证据，可以回答这个问题：{question.strip()}\n\n"
        "可用证据显示：\n"
        + "\n".join(evidence_lines)
        + "\n\n"
        "因此，后续写作或规划时应只围绕这些已引用材料展开；如果需要更强结论，请继续补充课程 brief、rubric 或研究来源。"
    )


def _assignment_augmented_query(request: AssignmentQARequest) -> str:
    parts = [request.question]
    if request.assignment:
        parts.extend(
            item
            for item in [
                request.assignment.course_code,
                request.assignment.title,
                request.assignment.objective,
                *request.assignment.deliverables[:3],
            ]
            if item
        )
    return " ".join(parts)


def _source_type(candidate: RetrievalCandidate) -> str | None:
    value = candidate.metadata.get("source_type")
    return str(value) if value is not None else None


def _terms(text: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", text.lower())
        if len(term) >= 2 and term not in {"the", "and", "for", "with", "that", "this", "from"}
    }


def _sentences(content: str) -> list[str]:
    normalized = " ".join(content.split())
    sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", normalized) if part.strip()]
    if sentences:
        return sentences
    return [normalized] if normalized else []


def _truncate_quote(text: str, max_length: int = 320) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_length:
        return compact
    return compact[:max_length].rstrip()


def _citation_confidence(score: float, quote: str) -> float:
    length_boost = min(len(quote) / 400, 0.2)
    return min(round(0.65 * score + 0.25 + length_boost, 3), 1.0)


def _overall_confidence(citations: list[AssignmentQACitation]) -> float:
    if not citations:
        return 0.0
    return round(sum(citation.evidence.confidence for citation in citations) / len(citations), 3)


def _citation_location(evidence: EvidenceRef) -> str:
    parts = [evidence.source_name or evidence.source_file_id or "unknown source"]
    if evidence.page is not None:
        parts.append(f"page {evidence.page}")
    if evidence.slide is not None:
        parts.append(f"slide {evidence.slide}")
    if evidence.section:
        parts.append(f"section {evidence.section}")
    return ", ".join(parts)
