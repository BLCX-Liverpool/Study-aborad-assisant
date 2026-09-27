from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tracing import capture_current_latency_span
from app.documents.chunking import chunk_document
from app.documents.parser import DoclingDocumentParser
from app.rag.embeddings import EmbeddingService
from app.rag.models import IndexDocumentRequest, IndexDocumentResponse
from app.rag.repository import DocumentChunkRepository, StoredFileRepository


class RagIndexingService:
    def __init__(
        self,
        parser: DoclingDocumentParser,
        embeddings: EmbeddingService,
        session: AsyncSession,
    ) -> None:
        self.parser = parser
        self.embeddings = embeddings
        self.session = session

    async def index_document(self, request: IndexDocumentRequest) -> IndexDocumentResponse:
        source_path = Path(request.source_path)
        async with capture_current_latency_span(
            span_name="rag.document_parse",
            span_type="document_parse",
            input_json={
                "file_id": request.file_id,
                "source_name": request.source_name or source_path.name,
                "mime_type": request.mime_type,
            },
        ) as span_output:
            parsed = self.parser.parse(
                source_path=source_path,
                file_id=request.file_id,
                source_name=request.source_name,
                mime_type=request.mime_type,
            )
            span_output["element_count"] = len(parsed.elements)
            span_output["parse_strategy"] = parsed.metadata.get("parse_strategy")
            span_output["ocr_status"] = parsed.metadata.get("ocr", {}).get("status")
        async with capture_current_latency_span(
            span_name="rag.chunk_document",
            span_type="rag",
            input_json={"file_id": request.file_id, "element_count": len(parsed.elements)},
        ) as span_output:
            chunks = chunk_document(parsed)
            span_output["chunk_count"] = len(chunks)
        for chunk in chunks:
            chunk.source_metadata["source_type"] = request.source_type
            chunk.source_metadata.setdefault("source_name", request.source_name or source_path.name)
            chunk.source_metadata.setdefault("mime_type", request.mime_type)
        async with capture_current_latency_span(
            span_name="rag.embedding_chunks",
            span_type="rag",
            input_json={"file_id": request.file_id, "chunk_count": len(chunks)},
        ) as span_output:
            embeddings = await self.embeddings.embed_texts([chunk.content for chunk in chunks])
            span_output["embedding_count"] = len(embeddings)

        async with capture_current_latency_span(
            span_name="rag.persist_index",
            span_type="db",
            input_json={"file_id": request.file_id, "chunk_count": len(chunks)},
        ) as span_output:
            file_repository = StoredFileRepository(self.session)
            await file_repository.upsert_file(
                file_id=request.file_id,
                user_id=request.user_id,
                filename=request.source_name or source_path.name,
                mime_type=request.mime_type,
                storage_path=str(source_path),
                source_type=request.source_type,
                checksum="indexed-from-existing-file",
            )

            chunk_repository = DocumentChunkRepository(self.session)
            await chunk_repository.replace_chunks(
                user_id=request.user_id,
                chunks=chunks,
                embeddings=embeddings,
            )
            await self.session.commit()
            span_output["persisted_chunks"] = len(chunks)

        return IndexDocumentResponse(
            file_id=request.file_id,
            chunk_count=len(chunks),
            embedding_count=len(embeddings),
        )
