from app.agents.assignment.idea_verifier import AssignmentIdeaVerifier
from app.agents.assignment.qa import AssignmentQAService
from app.agents.research.query_generator import ResearchQueryGenerator
from app.schemas.assignment import AssignmentQARequest
from app.schemas.research import (
    AssignmentResearchEvidenceReviewRequest,
    AssignmentResearchEvidenceReviewResponse,
    IdeaVerificationRequest,
    IdeaVerificationResponse,
    ResearchQueryRequest,
    ResearchSynthesisReport,
    ResearchSynthesisSource,
)


class AssignmentResearchEvidenceReviewService:
    def __init__(
        self,
        qa_service: AssignmentQAService,
        query_generator: ResearchQueryGenerator | None = None,
        idea_verifier: AssignmentIdeaVerifier | None = None,
    ) -> None:
        self.qa_service = qa_service
        self.query_generator = query_generator or ResearchQueryGenerator()
        self.idea_verifier = idea_verifier or AssignmentIdeaVerifier()

    async def review(
        self,
        request: AssignmentResearchEvidenceReviewRequest,
    ) -> AssignmentResearchEvidenceReviewResponse:
        queries = self._queries(request)
        qa_results = [
            await self.qa_service.answer(
                AssignmentQARequest(
                    user_id=request.user_id,
                    question=query,
                    file_ids=request.indexed_file_ids,
                    assignment=request.assignment,
                    top_k=8,
                    min_score=request.min_score,
                    min_citations=1,
                    include_research_sources=True,
                    conversation_id=request.conversation_id,
                    trace_id=request.trace_id,
                )
            )
            for query in queries
        ]

        idea_verification = await self._verify_ideas(request)
        synthesis = synthesize_research_review(
            qa_results=qa_results,
            idea_verification=idea_verification,
            indexed_file_ids=request.indexed_file_ids,
            research_sources=request.research_sources,
        )
        assumptions = [
            "Research evidence review uses already indexed RAG chunks for grounded QA.",
            "External search results must be selected and indexed before they can support final claims.",
        ]
        if not request.indexed_file_ids:
            assumptions.append("No indexed_file_ids were provided, so retrieval searched all user-accessible chunks.")

        return AssignmentResearchEvidenceReviewResponse(
            queries=queries,
            qa_results=qa_results,
            idea_verification=idea_verification,
            synthesis=synthesis,
            assumptions=assumptions,
            next_actions=_next_actions(synthesis),
        )

    def _queries(self, request: AssignmentResearchEvidenceReviewRequest) -> list[str]:
        if request.questions:
            return list(dict.fromkeys(question.strip() for question in request.questions if question.strip()))[
                : request.max_questions
            ]
        generated = self.query_generator.generate(
            ResearchQueryRequest(assignment=request.assignment, max_queries=request.max_questions)
        )
        return generated.queries

    async def _verify_ideas(
        self,
        request: AssignmentResearchEvidenceReviewRequest,
    ) -> IdeaVerificationResponse | None:
        ideas = request.ideas or request.assignment.possible_ideas
        if not ideas:
            return None
        return await self.idea_verifier.verify_async(
            IdeaVerificationRequest(
                assignment=request.assignment,
                ideas=ideas,
                research_sources=request.research_sources,
            )
        )


def synthesize_research_review(
    *,
    qa_results,
    idea_verification: IdeaVerificationResponse | None,
    indexed_file_ids: list[str] | None,
    research_sources,
) -> ResearchSynthesisReport:
    answered = [result for result in qa_results if result.status == "answered"]
    insufficient = [result for result in qa_results if result.status == "insufficient_evidence"]
    key_findings = []
    evidence_gaps = []

    for result in answered:
        first_quote = result.citations[0].evidence.quote if result.citations else None
        if first_quote:
            key_findings.append(f"{result.question}: {first_quote}")

    for result in insufficient:
        evidence_gaps.append(result.question)

    if idea_verification:
        for finding in idea_verification.findings:
            if finding.status == "supported":
                key_findings.append(f"Idea supported: {finding.idea}")
            elif finding.status == "needs_more_evidence":
                evidence_gaps.append(f"Idea needs more evidence: {finding.idea}")
            elif finding.status == "conflicts_with_constraints":
                evidence_gaps.append(f"Idea conflicts with assignment constraints: {finding.idea}")

    status = "insufficient_evidence"
    if answered and not evidence_gaps:
        status = "supported"
    elif answered:
        status = "partial"

    return ResearchSynthesisReport(
        status=status,
        key_findings=key_findings,
        evidence_gaps=evidence_gaps,
        selected_sources=_selected_sources(qa_results, research_sources),
        writing_guidance=_writing_guidance(status, bool(indexed_file_ids), bool(research_sources)),
    )


def _selected_sources(qa_results, research_sources) -> list[ResearchSynthesisSource]:
    by_title: dict[str, ResearchSynthesisSource] = {}
    for result in qa_results:
        for citation in result.citations:
            title = citation.evidence.source_name or citation.evidence.source_file_id or citation.chunk_id
            existing = by_title.get(title)
            if existing:
                existing.evidence_count += 1
                continue
            by_title[title] = ResearchSynthesisSource(
                title=title,
                source_type=citation.source_type,
                evidence_count=1,
            )

    for source in research_sources:
        existing = by_title.get(source.title)
        if existing:
            existing.url = source.url
            existing.summary = source.summary
            existing.source_type = existing.source_type or source.source_type
            continue
        by_title[source.title] = ResearchSynthesisSource(
            title=source.title,
            url=source.url,
            source_type=source.source_type,
            summary=source.summary,
            evidence_count=0,
        )
    return list(by_title.values())


def _writing_guidance(status: str, has_indexed_sources: bool, has_research_sources: bool) -> list[str]:
    guidance = [
        "Use only cited assignment chunks or indexed research chunks for claims in the draft.",
        "Keep uncited ideas as hypotheses until they pass evidence review.",
    ]
    if status != "supported":
        guidance.append("Resolve evidence gaps before finalizing thesis, literature review, or methodology choices.")
    if has_research_sources and not has_indexed_sources:
        guidance.append("Index selected research PDFs/web pages before using them as final evidence.")
    return guidance


def _next_actions(synthesis: ResearchSynthesisReport) -> list[str]:
    if synthesis.status == "supported":
        return ["Proceed to outline or draft using the cited evidence and supported ideas."]
    if synthesis.status == "partial":
        return ["Index additional sources for the listed evidence gaps.", "Re-run evidence review before drafting."]
    return [
        "Upload or index the assignment brief, rubric, and selected research sources.",
        "Run research search and index-source before asking for synthesis again.",
    ]
