from app.schemas.assignment import AssignmentAnalysis
from app.schemas.research import ResearchQueryRequest, ResearchQueryResponse


class ResearchQueryGenerator:
    def generate(self, request: ResearchQueryRequest) -> ResearchQueryResponse:
        queries = list(dict.fromkeys(query.strip() for query in request.assignment.research_queries if query.strip()))
        assumptions: list[str] = []

        if not queries:
            seeds = [
                request.assignment.objective,
                *request.assignment.deliverables,
                *[requirement.content for requirement in request.assignment.marking_criteria[:3]],
            ]
            queries = [_compact_query(seed) for seed in seeds if seed.strip()]
            assumptions.append("Generated research queries from assignment objective, deliverables, and marking criteria.")

        return ResearchQueryResponse(
            queries=queries[: request.max_queries],
            assumptions=assumptions,
        )


def _compact_query(text: str) -> str:
    words = text.replace("\n", " ").split()
    return " ".join(words[:12])
