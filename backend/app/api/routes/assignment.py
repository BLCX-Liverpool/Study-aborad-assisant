from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assignment.idea_verifier import AssignmentIdeaVerifier
from app.agents.assignment.qa import AssignmentQAService
from app.agents.research.arxiv import ArxivSearchClient
from app.agents.research.closure import AssignmentResearchEvidenceReviewService
from app.agents.research.paper import PaperRetrievalClient
from app.agents.research.query_generator import ResearchQueryGenerator
from app.agents.research.source_selection import SelectedResearchSourceIndexer
from app.agents.research.web_search import WebSearchClient
from app.agents.research.workflow import AssignmentResearchWorkflow
from app.core.database import get_session
from app.core.llm import get_llm_client, get_stage_llm_client
from app.documents.parser import DoclingDocumentParser
from app.rag.embeddings import EmbeddingService
from app.rag.indexer import RagIndexingService
from app.rag.models import IndexDocumentResponse
from app.rag.repository import DocumentChunkRepository
from app.rag.retriever import HybridRetrievalService
from app.schemas.assignment import AssignmentQARequest, AssignmentQAResponse
from app.schemas.research import (
    AssignmentResearchEvidenceReviewRequest,
    AssignmentResearchEvidenceReviewResponse,
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
    SelectedResearchSourceIndexRequest,
    SelectedResearchSourceIndexResponse,
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


@router.post("/qa", response_model=AssignmentQAResponse)
async def answer_assignment_question(
    request: AssignmentQARequest,
    session: AsyncSession = Depends(get_session),
) -> AssignmentQAResponse:
    return await AssignmentQAService(
        HybridRetrievalService(
            repository=DocumentChunkRepository(session),
            embeddings=EmbeddingService(get_llm_client()),
        )
    ).answer(request)


@router.post("/research/evidence-review", response_model=AssignmentResearchEvidenceReviewResponse)
async def review_assignment_research_evidence(
    request: AssignmentResearchEvidenceReviewRequest,
    session: AsyncSession = Depends(get_session),
) -> AssignmentResearchEvidenceReviewResponse:
    qa_service = AssignmentQAService(
        HybridRetrievalService(
            repository=DocumentChunkRepository(session),
            embeddings=EmbeddingService(get_llm_client()),
        )
    )
    return await AssignmentResearchEvidenceReviewService(
        qa_service=qa_service,
        idea_verifier=AssignmentIdeaVerifier(get_stage_llm_client("assignment")),
    ).review(request)


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


@router.post("/research/index-selected-arxiv", response_model=SelectedResearchSourceIndexResponse)
async def index_selected_arxiv_sources(
    request: SelectedResearchSourceIndexRequest,
    session: AsyncSession = Depends(get_session),
) -> SelectedResearchSourceIndexResponse:
    return await SelectedResearchSourceIndexer(
        session=session,
        embeddings=EmbeddingService(get_llm_client()),
    ).index_selected(
        user_id=request.user_id,
        sources=request.sources,
        conversation_id=request.conversation_id,
        trace_id=request.trace_id,
    )


@router.post("/ideas/verify", response_model=IdeaVerificationResponse)
async def verify_ideas(request: IdeaVerificationRequest) -> IdeaVerificationResponse:
    return await AssignmentIdeaVerifier(get_stage_llm_client("assignment")).verify_async(request)
