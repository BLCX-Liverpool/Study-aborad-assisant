from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assignment.idea_verifier import AssignmentIdeaVerifier
from app.agents.research.arxiv import ArxivSearchClient
from app.agents.research.paper import PaperRetrievalClient
from app.agents.research.query_generator import ResearchQueryGenerator
from app.agents.research.web_search import WebSearchClient
from app.agents.research.workflow import AssignmentResearchWorkflow
from app.core.database import get_session
from app.core.llm import get_llm_client, get_stage_llm_client
from app.documents.parser import DoclingDocumentParser
from app.rag.embeddings import EmbeddingService
from app.rag.indexer import RagIndexingService
from app.rag.models import IndexDocumentResponse
from app.schemas.research import (
    ArxivSearchRequest,
    ArxivSearchResponse,
    IdeaVerificationRequest,
    IdeaVerificationResponse,
    PaperDownloadRequest,
    PaperDownloadResponse,
    ResearchQueryRequest,
    ResearchQueryResponse,
    ResearchSourceIndexRequest,
    ResearchWorkflowRequest,
    ResearchWorkflowResponse,
    WebSearchRequest,
    WebSearchResponse,
)

router = APIRouter()


@router.post("/research/queries", response_model=ResearchQueryResponse)
async def generate_research_queries(request: ResearchQueryRequest) -> ResearchQueryResponse:
    return ResearchQueryGenerator().generate(request)


@router.post("/research/arxiv", response_model=ArxivSearchResponse)
async def search_arxiv(request: ArxivSearchRequest) -> ArxivSearchResponse:
    return await ArxivSearchClient().search(request)


@router.post("/research/web", response_model=WebSearchResponse)
async def search_web(request: WebSearchRequest) -> WebSearchResponse:
    return await WebSearchClient().search(request)


@router.post("/research/papers/download", response_model=PaperDownloadResponse)
async def download_paper(request: PaperDownloadRequest) -> PaperDownloadResponse:
    return await PaperRetrievalClient().download(request)


@router.post("/research/workflow", response_model=ResearchWorkflowResponse)
async def run_research_workflow(request: ResearchWorkflowRequest) -> ResearchWorkflowResponse:
    return await AssignmentResearchWorkflow().run(request)


@router.post("/research/index-source", response_model=IndexDocumentResponse)
async def index_research_source(
    request: ResearchSourceIndexRequest,
    session: AsyncSession = Depends(get_session),
):
    from app.rag.models import IndexDocumentRequest

    return await RagIndexingService(
        parser=DoclingDocumentParser(),
        embeddings=EmbeddingService(get_llm_client()),
        session=session,
    ).index_document(
        IndexDocumentRequest(
            user_id=request.user_id,
            file_id=request.file_id,
            source_path=str(request.source_path),
            source_name=request.source_name,
            mime_type=request.mime_type,
            source_type="research_source",
        )
    )


@router.post("/ideas/verify", response_model=IdeaVerificationResponse)
async def verify_ideas(request: IdeaVerificationRequest) -> IdeaVerificationResponse:
    return await AssignmentIdeaVerifier(get_stage_llm_client("assignment")).verify_async(request)
