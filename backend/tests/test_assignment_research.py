from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.agents.assignment.idea_verifier import AssignmentIdeaVerifier
from app.agents.assignment.qa import AssignmentQAService, validate_exact_quote
from app.agents.research.closure import AssignmentResearchEvidenceReviewService
from app.agents.research.arxiv import parse_arxiv_atom
from app.agents.research.query_generator import ResearchQueryGenerator
from app.agents.research.source_selection import SelectedResearchSourceIndexer
from app.agents.research.web_search import parse_duckduckgo_html
from app.documents.models import DocumentContentType, ParsedDocument, ParsedDocumentElement, ParseStrategy
from app.documents.ocr import DeepdocOcrEngine, OcrDocumentProcessor, OcrPageResult
from app.documents.parser import DoclingDocumentParser
from app.rag.indexer import RagIndexingService
from app.rag.models import HybridRetrievalResponse, IndexDocumentRequest, RetrievalCandidate
from app.schemas.assignment import AssignmentAnalysis, AssignmentQARequest, AssignmentRequirement
from app.schemas.research import (
    AssignmentResearchEvidenceReviewRequest,
    IdeaVerificationRequest,
    PaperDownloadResponse,
    ResearchQueryRequest,
    ResearchSource,
)


def test_research_query_generator_uses_assignment_fields() -> None:
    assignment = AssignmentAnalysis(
        objective="Evaluate retrieval augmented generation in higher education.",
        deliverables=["Research report"],
    )

    response = ResearchQueryGenerator().generate(ResearchQueryRequest(assignment=assignment))

    assert response.queries
    assert "retrieval" in response.queries[0].lower()


def test_parse_arxiv_atom_returns_sources() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2401.00001v1</id>
        <updated>2024-01-01T00:00:00Z</updated>
        <published>2024-01-01T00:00:00Z</published>
        <title>Retrieval Augmented Generation for Education</title>
        <summary>We study RAG systems in education.</summary>
        <author><name>Alice Example</name></author>
        <link href="http://arxiv.org/pdf/2401.00001v1" rel="related" title="pdf"/>
      </entry>
    </feed>
    """

    sources = parse_arxiv_atom(xml)

    assert len(sources) == 1
    assert sources[0].source_type == "arxiv"
    assert sources[0].url.endswith("2401.00001v1")
    assert sources[0].authors == ["Alice Example"]


def test_parse_duckduckgo_html_returns_sources() -> None:
    html = '<a rel="nofollow" class="result__a" href="https://example.edu/rag">RAG in Education</a>'

    sources = parse_duckduckgo_html(html, max_results=3)

    assert len(sources) == 1
    assert sources[0].source_type == "web"
    assert sources[0].title == "RAG in Education"


def test_ocr_processor_appends_deepdoc_results_when_needed() -> None:
    class FakeOcrEngine:
        def extract(self, source_path: Path):
            return [OcrPageResult(page=1, text="OCR extracted coursework text.", confidence=0.9)]

    parsed = ParsedDocument(
        file_id="file_1",
        source_name="scan.pdf",
        source_path=Path("scan.pdf"),
        elements=[
            ParsedDocumentElement(
                content_type=DocumentContentType.PARAGRAPH,
                text="",
                parse_strategy=ParseStrategy.FULL_OCR,
            )
        ],
        metadata={"parse_strategy": "full_ocr"},
    )

    processed = OcrDocumentProcessor(FakeOcrEngine()).apply_ocr_if_needed(parsed)

    assert processed.metadata["ocr"]["status"] == "applied"
    assert any(element.text == "OCR extracted coursework text." for element in processed.elements)


def test_deepdoc_engine_reads_subprocess_results(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "scan.pdf"
    source_path.write_bytes(b"%PDF placeholder")

    monkeypatch.setattr(
        "app.documents.ocr.check_deepdoc_runtime",
        lambda: type("Status", (), {"available": True, "message": "ok"})(),
    )
    monkeypatch.setattr(
        "app.documents.ocr._run_deepdoc_subprocess",
        lambda arguments: {
            "status": "ok",
            "results": [
                {
                    "page": 1,
                    "text": "DeepDoc extracted text.",
                    "confidence": 0.88,
                    "metadata": {"ocr_engine": "deepdoc", "parser": "PdfParser"},
                }
            ],
        },
    )

    results = DeepdocOcrEngine().extract(source_path)

    assert results[0].text == "DeepDoc extracted text."
    assert results[0].page == 1
    assert results[0].metadata["parser"] == "PdfParser"


def test_idea_verifier_marks_supported_and_conflicting_ideas() -> None:
    assignment = AssignmentAnalysis(
        objective="Write a report about RAG in education.",
        deliverables=["Report"],
        constraints=[
            AssignmentRequirement(
                requirement_type="constraint",
                content="No primary research interviews are allowed.",
            )
        ],
    )
    sources = [
        ResearchSource(
            source_type="arxiv",
            title="Retrieval augmented generation in education",
            url="https://arxiv.org/pdf/1",
            summary="A study of RAG in education.",
        )
    ]

    response = AssignmentIdeaVerifier().verify(
        IdeaVerificationRequest(
            assignment=assignment,
            ideas=["Evaluate RAG feedback in education", "Run group interviews with students"],
            research_sources=sources,
        )
    )

    assert response.findings[0].status == "supported"
    assert response.findings[1].status == "conflicts_with_constraints"


@pytest.mark.asyncio
async def test_assignment_qa_answers_only_with_validated_quotes() -> None:
    class FakeRetriever:
        async def retrieve(self, request):
            return HybridRetrievalResponse(
                query=request.query,
                candidates=[
                    RetrievalCandidate(
                        chunk_id="brief_1:0",
                        file_id="brief_1",
                        source_name="brief.pdf",
                        content=(
                            "The report must evaluate retrieval augmented generation in higher education. "
                            "The submission requires a 2,500 word critical report with Harvard referencing."
                        ),
                        score=0.92,
                        retrieval_type="hybrid",
                        page=2,
                        metadata={"source_type": "assignment_brief"},
                    )
                ],
            )

    response = await AssignmentQAService(FakeRetriever()).answer(
        AssignmentQARequest(
            user_id="user_1",
            question="What does the report need to evaluate?",
            file_ids=["brief_1"],
        )
    )

    assert response.status == "answered"
    assert response.citations[0].chunk_id == "brief_1:0"
    assert response.citations[0].evidence.quote in response.answer
    assert response.quote_validations[0].status == "passed"


@pytest.mark.asyncio
async def test_assignment_qa_rejects_low_quality_or_unquoted_evidence() -> None:
    class FakeRetriever:
        async def retrieve(self, request):
            return HybridRetrievalResponse(
                query=request.query,
                candidates=[
                    RetrievalCandidate(
                        chunk_id="brief_1:0",
                        file_id="brief_1",
                        source_name="brief.pdf",
                        content="Too short.",
                        score=0.05,
                        retrieval_type="bm25",
                        metadata={"source_type": "assignment_brief"},
                    )
                ],
            )

    response = await AssignmentQAService(FakeRetriever()).answer(
        AssignmentQARequest(
            user_id="user_1",
            question="What is the marking criterion?",
            min_score=0.2,
        )
    )

    assert response.status == "insufficient_evidence"
    assert response.citations == []
    assert response.source_quality[0].status == "rejected"


def test_assignment_quote_validation_requires_exact_substring() -> None:
    candidate = RetrievalCandidate(
        chunk_id="brief_1:0",
        file_id="brief_1",
        content="Students must submit a reflective report by Friday.",
        score=0.9,
        retrieval_type="hybrid",
        metadata={"source_type": "assignment_brief"},
    )

    validation = validate_exact_quote("When must students submit the report?", candidate)

    assert validation.status == "passed"
    assert validation.quote in candidate.content
    assert validation.start_char is not None


@pytest.mark.asyncio
async def test_research_evidence_review_links_rag_qa_synthesis_and_idea_verification() -> None:
    class FakeRetriever:
        async def retrieve(self, request):
            return HybridRetrievalResponse(
                query=request.query,
                candidates=[
                    RetrievalCandidate(
                        chunk_id="paper_1:0",
                        file_id="paper_1",
                        source_name="rag_paper.pdf",
                        content=(
                            "Retrieval augmented generation can improve feedback quality in higher education "
                            "when source grounding and citation checks are used."
                        ),
                        score=0.88,
                        retrieval_type="hybrid",
                        page=1,
                        metadata={"source_type": "research_source"},
                    )
                ],
            )

    assignment = AssignmentAnalysis(
        objective="Write a report about RAG feedback in higher education.",
        deliverables=["Critical report"],
        possible_ideas=["Evaluate RAG feedback quality in higher education"],
    )
    source = ResearchSource(
        source_type="paper_pdf",
        title="RAG feedback quality",
        url="https://example.edu/rag.pdf",
        summary="RAG and feedback in higher education.",
    )

    response = await AssignmentResearchEvidenceReviewService(
        qa_service=AssignmentQAService(FakeRetriever()),
        idea_verifier=AssignmentIdeaVerifier(),
    ).review(
        AssignmentResearchEvidenceReviewRequest(
            user_id="user_1",
            assignment=assignment,
            indexed_file_ids=["paper_1"],
            research_sources=[source],
            questions=["What evidence supports RAG feedback quality?"],
        )
    )

    assert response.qa_results[0].status == "answered"
    assert response.synthesis.status == "supported"
    assert response.synthesis.key_findings
    assert response.idea_verification is not None
    assert response.idea_verification.findings[0].status == "supported"


@pytest.mark.asyncio
async def test_research_source_indexing_marks_source_type(monkeypatch, tmp_path) -> None:
    captured = {}
    source_path = tmp_path / "paper.txt"
    source_path.write_text("Retrieval augmented generation evidence for education.", encoding="utf-8")

    class FakeParser:
        def parse(self, source_path: Path, file_id: str, source_name: str | None, mime_type: str | None):
            return ParsedDocument(
                file_id=file_id,
                source_name=source_name or source_path.name,
                source_path=source_path,
                mime_type=mime_type,
                elements=[
                    ParsedDocumentElement(
                        content_type=DocumentContentType.PARAGRAPH,
                        text=source_path.read_text(encoding="utf-8"),
                    )
                ],
            )

    class FakeEmbeddings:
        async def embed_texts(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

    class FakeStoredFileRepository:
        def __init__(self, session):
            self.session = session

        async def upsert_file(self, **kwargs):
            captured["file"] = kwargs

    class FakeChunkRepository:
        def __init__(self, session):
            self.session = session

        async def replace_chunks(self, user_id, chunks, embeddings):
            captured["chunks"] = chunks
            captured["embeddings"] = embeddings

    class FakeSession:
        async def commit(self):
            captured["committed"] = True

    monkeypatch.setattr("app.rag.indexer.StoredFileRepository", FakeStoredFileRepository)
    monkeypatch.setattr("app.rag.indexer.DocumentChunkRepository", FakeChunkRepository)

    response = await RagIndexingService(FakeParser(), FakeEmbeddings(), FakeSession()).index_document(
        IndexDocumentRequest(
            user_id="user_1",
            file_id="research_1",
            source_path=str(source_path),
            source_name="paper.txt",
            mime_type="text/plain",
            source_type="research_source",
        )
    )

    assert response.chunk_count == 1
    assert captured["file"]["source_type"] == "research_source"
    assert captured["chunks"][0].source_metadata["source_type"] == "research_source"
    assert captured["committed"] is True


@pytest.mark.asyncio
async def test_selected_arxiv_sources_download_and_index_after_confirmation(monkeypatch, tmp_path) -> None:
    captured = {}
    downloaded = tmp_path / "paper.pdf"
    downloaded.write_text("RAG evidence from selected ArXiv paper.", encoding="utf-8")

    class FakeDownloader:
        async def download(self, request):
            captured["download_request"] = request
            return PaperDownloadResponse(
                url=request.url,
                local_path=downloaded,
                content_type="application/pdf",
                bytes_written=downloaded.stat().st_size,
                sha256="abc",
                title="Selected paper",
            )

    class FakeParser:
        def parse(self, source_path: Path, file_id: str, source_name: str | None, mime_type: str | None):
            return ParsedDocument(
                file_id=file_id,
                source_name=source_name,
                source_path=source_path,
                mime_type=mime_type,
                elements=[
                    ParsedDocumentElement(
                        content_type=DocumentContentType.PARAGRAPH,
                        text=downloaded.read_text(encoding="utf-8"),
                    )
                ],
            )

    class FakeEmbeddings:
        async def embed_texts(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

    class FakeStoredFileRepository:
        def __init__(self, session):
            self.session = session

        async def upsert_file(self, **kwargs):
            captured["file"] = kwargs

    class FakeChunkRepository:
        def __init__(self, session):
            self.session = session

        async def replace_chunks(self, user_id, chunks, embeddings):
            captured["chunks"] = chunks
            captured["embeddings"] = embeddings

    class FakeSession:
        async def commit(self):
            captured["committed"] = True

    monkeypatch.setattr("app.rag.indexer.StoredFileRepository", FakeStoredFileRepository)
    monkeypatch.setattr("app.rag.indexer.DocumentChunkRepository", FakeChunkRepository)

    source = ResearchSource(
        source_type="arxiv",
        title="Retrieval Augmented Generation for Education",
        url="https://arxiv.org/pdf/2401.00001",
        summary="RAG in education.",
    )

    response = await SelectedResearchSourceIndexer(
        session=FakeSession(),
        embeddings=FakeEmbeddings(),
        parser=FakeParser(),
        downloader=FakeDownloader(),
        output_root=tmp_path / "research_sources",
    ).index_selected(user_id="user_1", sources=[source])

    assert response.indexed_file_ids
    assert response.results[0].status == "indexed"
    assert captured["download_request"].url == source.url
    assert captured["file"]["source_type"] == "research_source"
    assert captured["chunks"][0].source_metadata["source_type"] == "research_source"
    assert captured["committed"] is True


@pytest.mark.asyncio
async def test_selected_non_arxiv_source_is_not_downloaded(tmp_path) -> None:
    source = ResearchSource(
        source_type="web",
        title="Web source",
        url="https://example.com/source",
    )

    response = await SelectedResearchSourceIndexer(
        session=object(),
        embeddings=object(),
        output_root=tmp_path,
    ).index_selected(user_id="user_1", sources=[source])

    assert response.indexed_file_ids == []
    assert response.results[0].status == "skipped"


@pytest.mark.asyncio
async def test_research_source_indexing_postgres_integration_when_configured(monkeypatch, tmp_path) -> None:
    import os

    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL/pgvector RAG indexing integration test.")

    source_path = tmp_path / "paper.txt"
    source_path.write_text("RAG evaluation in education research source.", encoding="utf-8")
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        with open(Path(__file__).parents[1] / "app/db/migrations/001_initial_schema.sql", encoding="utf-8") as f:
            migration_sql = f.read()
        for statement in migration_sql.split(";"):
            if statement.strip():
                await session.execute(text(statement))
        await session.commit()

        class FakeEmbeddings:
            async def embed_texts(self, texts):
                return [[0.1, 0.2, 0.3] for _ in texts]

        response = await RagIndexingService(
            parser=DoclingDocumentParser(),
            embeddings=FakeEmbeddings(),
            session=session,
        ).index_document(
            IndexDocumentRequest(
                user_id="user_1",
                file_id="research_pg_1",
                source_path=str(source_path),
                source_name="paper.txt",
                mime_type="text/plain",
                source_type="research_source",
            )
        )

    await engine.dispose()
    assert response.chunk_count >= 1
