from app.agents.research.arxiv import ArxivSearchClient
from app.agents.research.query_generator import ResearchQueryGenerator
from app.agents.research.web_search import WebSearchClient
from app.schemas.research import (
    ArxivSearchRequest,
    ResearchQueryRequest,
    ResearchWorkflowRequest,
    ResearchWorkflowResponse,
    WebSearchRequest,
)


class AssignmentResearchWorkflow:
    def __init__(
        self,
        query_generator: ResearchQueryGenerator | None = None,
        arxiv_client: ArxivSearchClient | None = None,
        web_client: WebSearchClient | None = None,
    ) -> None:
        self.query_generator = query_generator or ResearchQueryGenerator()
        self.arxiv_client = arxiv_client or ArxivSearchClient()
        self.web_client = web_client or WebSearchClient()

    async def run(self, request: ResearchWorkflowRequest) -> ResearchWorkflowResponse:
        query_response = self.query_generator.generate(
            ResearchQueryRequest(
                assignment=request.assignment,
                max_queries=5,
            )
        )
        sources = []
        assumptions = list(query_response.assumptions)

        for query in query_response.queries:
            if request.include_arxiv:
                try:
                    arxiv_response = await self.arxiv_client.search(
                        ArxivSearchRequest(query=query, max_results=request.max_results_per_query)
                    )
                    sources.extend(arxiv_response.sources)
                except Exception as exc:
                    assumptions.append(f"ArXiv search failed for {query!r}: {exc}")
            if request.include_web:
                web_response = await self.web_client.search(
                    WebSearchRequest(query=query, max_results=request.max_results_per_query)
                )
                sources.extend(web_response.sources)
                assumptions.extend(web_response.assumptions)

        return ResearchWorkflowResponse(
            queries=query_response.queries,
            sources=_deduplicate_sources(sources),
            assumptions=assumptions,
        )


def _deduplicate_sources(sources):
    seen: set[str] = set()
    deduped = []
    for source in sources:
        if source.url in seen:
            continue
        seen.add(source.url)
        deduped.append(source)
    return deduped
