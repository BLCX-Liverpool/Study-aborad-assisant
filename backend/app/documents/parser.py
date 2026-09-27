from pathlib import Path

from app.documents.models import (
    DocumentContentType,
    ParsedDocument,
    ParsedDocumentElement,
    ParseStrategy,
)
from app.documents.ocr import ConfiguredOcrEngine, OcrDocumentProcessor
from app.documents.page_quality import analyze_native_text, calculate_text_quality, choose_parse_strategy


SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".pptx"}


class DocumentParserError(RuntimeError):
    pass


class DoclingDocumentParser:
    """Docling-backed parser for PDF, DOCX, and PPTX.

    The adapter keeps a stable internal document model for downstream assignment
    extraction and RAG. OCR execution is handled by the Deepdoc adapter; this
    parser records the strategy metadata that decides whether OCR is needed.
    """

    def parse(
        self,
        source_path: Path,
        file_id: str,
        source_name: str | None = None,
        mime_type: str | None = None,
    ) -> ParsedDocument:
        source_path = Path(source_path)
        if source_path.suffix.lower() not in SUPPORTED_DOCUMENT_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
            raise DocumentParserError(
                f"Unsupported document type {source_path.suffix!r}. Supported: {supported}."
            )

        try:
            markdown = self._convert_to_markdown(source_path)
        except ImportError as exc:
            raise DocumentParserError(
                "Docling is required for PDF/DOCX/PPTX parsing. Install backend dependencies first."
            ) from exc

        elements = markdown_to_elements(markdown)
        metrics = analyze_native_text(markdown)
        parse_strategy = choose_parse_strategy(metrics)
        text_quality_score = calculate_text_quality(markdown)
        for element in elements:
            element.parse_strategy = parse_strategy
            element.text_quality_score = text_quality_score
            element.image_area_ratio = metrics.image_area_ratio

        parsed = ParsedDocument(
            file_id=file_id,
            source_name=source_name or source_path.name,
            source_path=source_path,
            mime_type=mime_type,
            elements=elements,
            metadata={
                "parser": "docling",
                "text_quality_score": text_quality_score,
                "page_quality_metrics": metrics.model_dump(),
                "parse_strategy": parse_strategy.value,
            },
        )
        if parse_strategy in {ParseStrategy.REGION_OCR, ParseStrategy.FULL_OCR}:
            return self._apply_deepdoc_ocr(parsed)
        return parsed

    def _apply_deepdoc_ocr(self, parsed: ParsedDocument) -> ParsedDocument:
        try:
            return OcrDocumentProcessor(ConfiguredOcrEngine()).apply_ocr_if_needed(parsed)
        except Exception as exc:
            return parsed.model_copy(
                update={
                    "metadata": {
                        **parsed.metadata,
                        "ocr": {
                            "status": "unavailable",
                            "engine": "deepdoc",
                            "error": str(exc),
                        },
                    }
                }
            )

    def _convert_to_markdown(self, source_path: Path) -> str:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import HeadingHierarchyOptions, PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline_options = PdfPipelineOptions()
        pipeline_options.heading_hierarchy_options = HeadingHierarchyOptions(enabled=True)
        pipeline_options.generate_parsed_pages = True

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        result = converter.convert(str(source_path))
        return result.document.export_to_markdown()


def markdown_to_elements(markdown: str) -> list[ParsedDocumentElement]:
    elements: list[ParsedDocumentElement] = []
    section_path: list[str] = []
    paragraph_buffer: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_buffer:
            return
        text = "\n".join(paragraph_buffer).strip()
        paragraph_buffer.clear()
        if text:
            elements.append(
                ParsedDocumentElement(
                    content_type=DocumentContentType.PARAGRAPH,
                    text=text,
                    section=section_path[-1] if section_path else None,
                    section_path=list(section_path),
                )
            )

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            continue

        if line.startswith("#"):
            heading_marker, _, heading_text = line.partition(" ")
            if set(heading_marker) == {"#"} and heading_text.strip():
                flush_paragraph()
                level = len(heading_marker)
                section_path = section_path[: level - 1]
                section_path.append(heading_text.strip())
                elements.append(
                    ParsedDocumentElement(
                        content_type=(
                            DocumentContentType.TITLE
                            if level == 1 and len(elements) == 0
                            else DocumentContentType.SECTION
                        ),
                        text=heading_text.strip(),
                        section=heading_text.strip(),
                        section_path=list(section_path),
                        heading_level=level,
                    )
                )
                continue

        paragraph_buffer.append(line)

    flush_paragraph()
    return elements
