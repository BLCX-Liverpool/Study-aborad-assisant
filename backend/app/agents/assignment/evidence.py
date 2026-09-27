from app.documents.models import DocumentChunkDraft
from app.schemas.common import EvidenceRef


def evidence_from_chunk(
    chunk: DocumentChunkDraft,
    quote: str | None = None,
    confidence: float = 0.8,
) -> EvidenceRef:
    return EvidenceRef(
        source_file_id=chunk.file_id,
        source_name=chunk.source_name,
        page=chunk.page,
        slide=chunk.slide,
        section=chunk.section,
        quote=quote,
        confidence=confidence,
    )


def source_context_from_chunks(chunks: list[DocumentChunkDraft]) -> str:
    parts: list[str] = []
    for chunk in chunks:
        location = []
        if chunk.page is not None:
            location.append(f"page {chunk.page}")
        if chunk.slide is not None:
            location.append(f"slide {chunk.slide}")
        if chunk.section:
            location.append(f"section {chunk.section}")
        location_text = ", ".join(location) or "location unavailable"
        parts.append(
            f"[chunk={chunk.chunk_index}; file={chunk.source_name}; {location_text}]\n{chunk.content}"
        )
    return "\n\n---\n\n".join(parts)

