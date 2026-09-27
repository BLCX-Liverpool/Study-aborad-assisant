import json

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM
from app.schemas.assignment import AssignmentAnalysis
from app.schemas.research import (
    IdeaVerificationFinding,
    IdeaVerificationRequest,
    IdeaVerificationResponse,
    ResearchSource,
)


class AssignmentIdeaVerifier:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm

    def verify(self, request: IdeaVerificationRequest) -> IdeaVerificationResponse:
        ideas = request.ideas or request.assignment.possible_ideas
        findings = [
            _verify_idea(
                idea=idea,
                assignment=request.assignment,
                research_sources=request.research_sources,
            )
            for idea in ideas
        ]
        recommended = [
            finding.idea
            for finding in findings
            if finding.status == "supported"
        ]
        return IdeaVerificationResponse(findings=findings, recommended_ideas=recommended)

    async def verify_async(self, request: IdeaVerificationRequest) -> IdeaVerificationResponse:
        rule_response = self.verify(request)
        if self.llm is None:
            return rule_response
        try:
            llm_response = await self.llm.chat(
                ChatRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "Review assignment ideas against constraints and research sources. "
                                "Return JSON with findings array: idea, status, reasons, supporting_sources. "
                                "Allowed status: supported, needs_more_evidence, conflicts_with_constraints. Do not invent sources."
                            ),
                        ),
                        ChatMessage(
                            role="user",
                            content=json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
                        ),
                    ],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
            )
            payload = json.loads(llm_response.content)
            findings = payload.get("findings", [])
            if findings:
                response = IdeaVerificationResponse.model_validate(
                    {
                        "findings": findings,
                        "recommended_ideas": [
                            finding.get("idea")
                            for finding in findings
                            if finding.get("status") == "supported"
                        ],
                    }
                )
                return response
        except Exception:
            return rule_response
        return rule_response


def _verify_idea(
    *,
    idea: str,
    assignment: AssignmentAnalysis,
    research_sources: list[ResearchSource],
) -> IdeaVerificationFinding:
    reasons: list[str] = []
    supporting_sources: list[str] = []
    lowered = idea.lower()

    for requirement in assignment.constraints:
        if _conflicts_with_constraint(lowered, requirement.content.lower()):
            return IdeaVerificationFinding(
                idea=idea,
                status="conflicts_with_constraints",
                reasons=[f"Potentially conflicts with constraint: {requirement.content}"],
            )

    for source in research_sources:
        haystack = f"{source.title} {source.summary or ''}".lower()
        if _shares_terms(lowered, haystack):
            supporting_sources.append(source.title)

    if supporting_sources:
        reasons.append("Idea has at least one relevant research source.")
        if assignment.marking_criteria:
            reasons.append("Check alignment against marking criteria before final selection.")
        return IdeaVerificationFinding(
            idea=idea,
            status="supported",
            reasons=reasons,
            supporting_sources=supporting_sources[:5],
        )

    return IdeaVerificationFinding(
        idea=idea,
        status="needs_more_evidence",
        reasons=["No clearly matching research source was found for this idea."],
    )


def _conflicts_with_constraint(idea: str, constraint: str) -> bool:
    if "no primary research" in constraint and "interview" in idea:
        return True
    if "individual" in constraint and "group" in idea:
        return True
    return False


def _shares_terms(left: str, right: str) -> bool:
    left_terms = {term for term in left.split() if len(term) >= 4}
    right_terms = {term for term in right.split() if len(term) >= 4}
    return bool(left_terms & right_terms)
