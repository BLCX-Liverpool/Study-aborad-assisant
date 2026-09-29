from hashlib import sha256
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.research.paper import PaperRetrievalClient
from app.core.config import get_settings
from app.documents.parser import DoclingDocumentParser
from app.rag.embeddings import EmbeddingService
from app.rag.indexer import RagIndexingService
from app.rag.models import IndexDocumentRequest
from app.schemas.research import (
    PaperDownloadRequest,
    ResearchSource,
    SelectedResearchSourceIndexResponse,
    SelectedResearchSourceIndexResult,
)
from app.services.file_service import sanitize_filename


class SelectedResearchSourceIndexer:
    def __init__(
        self,
        *,
        session: AsyncSession,
        embeddings: EmbeddingService,
        parser: DoclingDocumentParser | None = None,
        downloader: PaperRetrievalClient | None = None,
        output_root: Path | None = None,
    ) -> None:
        settings = get_settings()
        self.session = session
        self.embeddings = embeddings
        self.parser = parser or DoclingDocumentParser()
        self.downloader = downloader or PaperRetrievalClient()
        self.output_root = output_root or settings.research_source_storage_dir

    async def index_selected(
        self,
        *,
        user_id: str,
        sources: list[ResearchSource],
        conversation_id: str | None = None,
        trace_id: str | None = None,
    ) -> SelectedResearchSourceIndexResponse:
        results: list[SelectedResearchSourceIndexResult] = []
        indexed_file_ids: list[str] = []
        output_dir = self.output_root / sanitize_filename(user_id)
        for source in sources:
            if source.source_type != "arxiv":
                results.append(
                    SelectedResearchSourceIndexResult(
                        source=source,
                        file_id=_file_id_for_source(source),
                        status="skipped",
                        error="Only ArXiv sources are supported by this confirmation flow.",
                    )
                )
                continue
            file_id = _file_id_for_source(source)
            filename = _filename_for_source(source, file_id)
            try:
                download = await self.downloader.download(
                    PaperDownloadRequest(
                        url=source.url,
                        output_dir=output_dir,
                        filename=filename,
                    )
                )
            except Exception as exc:
                results.append(
                    SelectedResearchSourceIndexResult(
                        source=source,
                        file_id=file_id,
                        status="download_failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            try:
                index = await RagIndexingService(
                    parser=self.parser,
                    embeddings=self.embeddings,
                    session=self.session,
                ).index_document(
                    IndexDocumentRequest(
                        user_id=user_id,
                        file_id=file_id,
                        source_path=str(download.local_path),
                        source_name=source.title,
                        mime_type=download.content_type or "application/pdf",
                        source_type="research_source",
                        conversation_id=conversation_id,
                        trace_id=trace_id,
                    )
                )
            except Exception as exc:
                results.append(
                    SelectedResearchSourceIndexResult(
                        source=source,
                        file_id=file_id,
                        local_path=download.local_path,
                        download=download,
                        status="index_failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            indexed_file_ids.append(file_id)
            results.append(
                SelectedResearchSourceIndexResult(
                    source=source,
                    file_id=file_id,
                    local_path=download.local_path,
                    download=download,
                    index=index,
                    status="indexed",
                )
            )
        return SelectedResearchSourceIndexResponse(
            user_id=user_id,
            indexed_file_ids=indexed_file_ids,
            results=results,
            assumptions=[
                "Selected ArXiv papers were downloaded only after user confirmation.",
                "Indexed research sources use source_type=research_source and can be retrieved by Assignment QA with include_research_sources=true.",
            ],
        )


def _file_id_for_source(source: ResearchSource) -> str:
    digest = sha256(source.url.encode("utf-8")).hexdigest()[:12]
    return f"arxiv_{digest}"


def _filename_for_source(source: ResearchSource, file_id: str) -> str:
    title = sanitize_filename(source.title.lower().replace(" ", "_"))[:80]
    return f"{file_id}_{title or 'paper'}.pdf"
