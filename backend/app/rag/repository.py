from collections.abc import Sequence

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentChunk, StoredFile
from app.documents.models import DocumentChunkDraft
from app.rag.models import RetrievalCandidate


def vector_literal(embedding: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.10f}" for value in embedding) + "]"


class DocumentChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replace_chunks(
        self,
        user_id: str,
        chunks: list[DocumentChunkDraft],
        embeddings: list[list[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk and embedding counts must match.")
        if not chunks:
            return

        file_id = chunks[0].file_id
        await self.session.execute(delete(DocumentChunk).where(DocumentChunk.file_id == file_id))

        insert_sql = text(
            """
            INSERT INTO document_chunks (
                id,
                file_id,
                user_id,
                chunk_index,
                page,
                slide,
                section,
                section_path,
                heading_level,
                content_type,
                content,
                token_count,
                bbox_json,
                parse_strategy,
                text_quality_score,
                image_area_ratio,
                source_metadata_json,
                embedding,
                metadata_json
            )
            VALUES (
                :id,
                :file_id,
                :user_id,
                :chunk_index,
                :page,
                :slide,
                :section,
                CAST(:section_path AS jsonb),
                :heading_level,
                :content_type,
                :content,
                :token_count,
                CAST(:bbox_json AS jsonb),
                :parse_strategy,
                :text_quality_score,
                :image_area_ratio,
                CAST(:source_metadata_json AS jsonb),
                CAST(:embedding AS vector),
                CAST(:metadata_json AS jsonb)
            )
            """
        )

        for chunk, embedding in zip(chunks, embeddings, strict=True):
            await self.session.execute(
                insert_sql,
                {
                    "id": f"{chunk.file_id}:{chunk.chunk_index}",
                    "file_id": chunk.file_id,
                    "user_id": user_id,
                    "chunk_index": chunk.chunk_index,
                    "page": chunk.page,
                    "slide": chunk.slide,
                    "section": chunk.section,
                    "section_path": _json_literal(chunk.section_path),
                    "heading_level": chunk.heading_level,
                    "content_type": chunk.content_type,
                    "content": chunk.content,
                    "token_count": chunk.token_count,
                    "bbox_json": _json_literal(chunk.bbox.model_dump() if chunk.bbox else None),
                    "parse_strategy": chunk.parse_strategy.value,
                    "text_quality_score": chunk.text_quality_score,
                    "image_area_ratio": chunk.image_area_ratio,
                    "source_metadata_json": _json_literal(chunk.source_metadata),
                    "embedding": vector_literal(embedding),
                    "metadata_json": _json_literal(
                        {
                            "source_name": chunk.source_name,
                            "content_type": chunk.content_type.value
                            if hasattr(chunk.content_type, "value")
                            else str(chunk.content_type),
                            "source_type": chunk.source_metadata.get("source_type"),
                        }
                    ),
                },
            )

    async def bm25_search(
        self,
        user_id: str,
        query: str,
        file_ids: list[str] | None,
        top_k: int,
    ) -> list[RetrievalCandidate]:
        file_filter = "AND dc.file_id = ANY(:file_ids)" if file_ids else ""
        sql = text(
            f"""
            SELECT
                dc.id,
                dc.file_id,
                f.filename AS source_name,
                dc.content,
                ts_rank_cd(dc.search_vector, websearch_to_tsquery('simple', :query)) AS score,
                dc.page,
                dc.slide,
                dc.section,
                dc.section_path,
                dc.metadata_json
            FROM document_chunks dc
            JOIN files f ON f.id = dc.file_id
            WHERE dc.user_id = :user_id
              {file_filter}
              AND dc.search_vector @@ websearch_to_tsquery('simple', :query)
            ORDER BY score DESC
            LIMIT :top_k
            """
        )
        result = await self.session.execute(
            sql,
            {
                "user_id": user_id,
                "query": query,
                "file_ids": file_ids,
                "top_k": top_k,
            },
        )
        return [_candidate_from_row(row, "bm25") for row in result.mappings()]

    async def vector_search(
        self,
        user_id: str,
        query_embedding: list[float],
        file_ids: list[str] | None,
        top_k: int,
    ) -> list[RetrievalCandidate]:
        file_filter = "AND dc.file_id = ANY(:file_ids)" if file_ids else ""
        sql = text(
            f"""
            SELECT
                dc.id,
                dc.file_id,
                f.filename AS source_name,
                dc.content,
                1 - (dc.embedding <=> CAST(:embedding AS vector)) AS score,
                dc.page,
                dc.slide,
                dc.section,
                dc.section_path,
                dc.metadata_json
            FROM document_chunks dc
            JOIN files f ON f.id = dc.file_id
            WHERE dc.user_id = :user_id
              {file_filter}
              AND dc.embedding IS NOT NULL
            ORDER BY dc.embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
            """
        )
        result = await self.session.execute(
            sql,
            {
                "user_id": user_id,
                "embedding": vector_literal(query_embedding),
                "file_ids": file_ids,
                "top_k": top_k,
            },
        )
        return [_candidate_from_row(row, "vector") for row in result.mappings()]


class StoredFileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_file(
        self,
        file_id: str,
        user_id: str,
        filename: str,
        mime_type: str | None,
        storage_path: str,
        source_type: str,
        checksum: str,
        conversation_id: str | None = None,
    ) -> None:
        existing = await self.session.get(StoredFile, file_id)
        if existing:
            existing.filename = filename
            existing.mime_type = mime_type
            existing.storage_path = storage_path
            existing.source_type = source_type
            existing.checksum = checksum
            existing.conversation_id = conversation_id
            return

        self.session.add(
            StoredFile(
                id=file_id,
                user_id=user_id,
                conversation_id=conversation_id,
                filename=filename,
                mime_type=mime_type,
                storage_path=storage_path,
                source_type=source_type,
                checksum=checksum,
            )
        )


def _candidate_from_row(row, retrieval_type: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=row["id"],
        file_id=row["file_id"],
        source_name=row["source_name"],
        content=row["content"],
        score=float(row["score"] or 0.0),
        retrieval_type=retrieval_type,
        page=row["page"],
        slide=row["slide"],
        section=row["section"],
        section_path=row["section_path"] or [],
        metadata=row["metadata_json"] or {},
    )


def _json_literal(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
