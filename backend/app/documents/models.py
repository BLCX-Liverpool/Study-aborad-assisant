from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ParseStrategy(StrEnum):
    NATIVE = "native"
    REGION_OCR = "region_ocr"
    FULL_OCR = "full_ocr"


class DocumentContentType(StrEnum):
    TITLE = "title"
    SECTION = "section"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    FIGURE = "figure"


class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class PageQualityMetrics(BaseModel):
    text_length: int = 0
    word_count: int = 0
    image_area_ratio: float = Field(default=0.0, ge=0.0)
    printable_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    replacement_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    text_area_ratio: float = Field(default=0.0, ge=0.0)
    vector_count: int = 0


class ParsedDocumentElement(BaseModel):
    content_type: DocumentContentType
    text: str
    page: int | None = None
    slide: int | None = None
    section: str | None = None
    section_path: list[str] = Field(default_factory=list)
    heading_level: int | None = None
    bbox: BoundingBox | None = None
    parse_strategy: ParseStrategy = ParseStrategy.NATIVE
    text_quality_score: float | None = None
    image_area_ratio: float | None = None
    source_metadata: dict = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    file_id: str
    source_name: str
    source_path: Path
    mime_type: str | None = None
    elements: list[ParsedDocumentElement] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class DocumentChunkDraft(BaseModel):
    file_id: str
    source_name: str
    chunk_index: int
    content: str
    content_type: Literal["paragraph", "table", "figure", "mixed"] = "paragraph"
    page: int | None = None
    slide: int | None = None
    section: str | None = None
    section_path: list[str] = Field(default_factory=list)
    heading_level: int | None = None
    bbox: BoundingBox | None = None
    parse_strategy: ParseStrategy = ParseStrategy.NATIVE
    text_quality_score: float | None = None
    image_area_ratio: float | None = None
    token_count: int | None = None
    source_metadata: dict = Field(default_factory=dict)

