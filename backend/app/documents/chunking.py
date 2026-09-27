from app.documents.models import DocumentChunkDraft, DocumentContentType, ParsedDocument, ParsedDocumentElement


def estimate_token_count(text: str) -> int:
    return max(1, len(text.split()))


def chunk_document(
    document: ParsedDocument,
    chunk_size: int = 3000,
    overlap: int = 300,
) -> list[DocumentChunkDraft]:
    chunks: list[DocumentChunkDraft] = []
    grouped: list[list[ParsedDocumentElement]] = []
    current_group: list[ParsedDocumentElement] = []
    current_section_path: list[str] | None = None

    for element in document.elements:
        if element.content_type in {DocumentContentType.TITLE, DocumentContentType.SECTION}:
            if current_group:
                grouped.append(current_group)
                current_group = []
            current_section_path = element.section_path
            current_group.append(element)
            continue

        if current_section_path is not None and element.section_path != current_section_path:
            if current_group:
                grouped.append(current_group)
            current_group = [element]
            current_section_path = element.section_path
            continue

        current_group.append(element)

    if current_group:
        grouped.append(current_group)

    for group in grouped:
        section_text = "\n\n".join(element.text for element in group if element.text.strip())
        if len(section_text) <= chunk_size:
            chunks.append(_chunk_from_group(document, len(chunks), group, section_text))
            continue

        chunks.extend(_split_large_group(document, len(chunks), group, chunk_size, overlap))

    return chunks


def _chunk_from_group(
    document: ParsedDocument,
    chunk_index: int,
    group: list[ParsedDocumentElement],
    content: str,
) -> DocumentChunkDraft:
    anchor = next((element for element in group if element.text.strip()), group[0])
    return DocumentChunkDraft(
        file_id=document.file_id,
        source_name=document.source_name,
        chunk_index=chunk_index,
        content=content,
        content_type="mixed" if len(group) > 1 else anchor.content_type.value,
        page=anchor.page,
        slide=anchor.slide,
        section=anchor.section,
        section_path=anchor.section_path,
        heading_level=anchor.heading_level,
        bbox=anchor.bbox,
        parse_strategy=anchor.parse_strategy,
        text_quality_score=anchor.text_quality_score,
        image_area_ratio=anchor.image_area_ratio,
        token_count=estimate_token_count(content),
        source_metadata=anchor.source_metadata,
    )


def _split_large_group(
    document: ParsedDocument,
    start_index: int,
    group: list[ParsedDocumentElement],
    chunk_size: int,
    overlap: int,
) -> list[DocumentChunkDraft]:
    chunks: list[DocumentChunkDraft] = []
    text = "\n\n".join(element.text for element in group if element.text.strip())
    start = 0

    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(_chunk_from_group(document, start_index + len(chunks), group, chunk_text))
        if end >= len(text):
            break
        start = end - overlap if 0 < overlap < chunk_size else end

    return chunks
