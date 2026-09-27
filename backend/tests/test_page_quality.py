from app.documents.ocr import OcrPageResult
from app.documents.models import PageQualityMetrics, ParseStrategy
from app.documents.parser import DoclingDocumentParser
from app.documents.page_quality import analyze_native_text, choose_parse_strategy


def test_choose_full_ocr_for_scan_like_page() -> None:
    metrics = PageQualityMetrics(text_length=10, image_area_ratio=0.9)
    assert choose_parse_strategy(metrics) == ParseStrategy.FULL_OCR


def test_choose_region_ocr_for_mixed_page() -> None:
    metrics = PageQualityMetrics(text_length=500, image_area_ratio=0.4, printable_ratio=0.98)
    assert choose_parse_strategy(metrics) == ParseStrategy.REGION_OCR


def test_analyze_native_text_counts_words() -> None:
    metrics = analyze_native_text("Submit a 3000 word report.")
    assert metrics.word_count == 5


def test_docling_parser_auto_applies_configured_ocr_when_strategy_needed(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "scan.pdf"
    source_path.write_bytes(b"%PDF scan placeholder")

    class FakeConfiguredOcrEngine:
        def extract(self, source_path):
            return [OcrPageResult(page=1, text="OCR text from configured runtime.", confidence=0.91)]

    monkeypatch.setattr(DoclingDocumentParser, "_convert_to_markdown", lambda self, path: "")
    monkeypatch.setattr("app.documents.parser.ConfiguredOcrEngine", FakeConfiguredOcrEngine)

    parsed = DoclingDocumentParser().parse(source_path=source_path, file_id="file_scan")

    assert parsed.metadata["parse_strategy"] == ParseStrategy.FULL_OCR.value
    assert parsed.metadata["ocr"]["status"] == "applied"
    assert any(element.text == "OCR text from configured runtime." for element in parsed.elements)
