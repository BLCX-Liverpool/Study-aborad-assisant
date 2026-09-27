from app.documents.models import PageQualityMetrics, ParseStrategy


def calculate_text_quality(text: str) -> float:
    if not text:
        return 0.0

    printable_count = sum(1 for char in text if char.isprintable())
    replacement_count = text.count("�")
    printable_ratio = printable_count / len(text)
    replacement_ratio = replacement_count / len(text)
    return max(0.0, min(1.0, printable_ratio - replacement_ratio))


def analyze_native_text(
    text: str,
    image_area_ratio: float = 0.0,
    text_area_ratio: float = 0.0,
    vector_count: int = 0,
) -> PageQualityMetrics:
    stripped = text.strip()
    text_length = len(stripped)
    word_count = len(stripped.split())
    printable_ratio = (
        sum(1 for char in stripped if char.isprintable()) / text_length
        if text_length
        else 0.0
    )
    replacement_ratio = stripped.count("�") / text_length if text_length else 0.0

    return PageQualityMetrics(
        text_length=text_length,
        word_count=word_count,
        image_area_ratio=image_area_ratio,
        printable_ratio=printable_ratio,
        replacement_ratio=replacement_ratio,
        text_area_ratio=text_area_ratio,
        vector_count=vector_count,
    )


def choose_parse_strategy(metrics: PageQualityMetrics) -> ParseStrategy:
    text_quality = max(0.0, metrics.printable_ratio - metrics.replacement_ratio)

    if metrics.text_length < 50 and metrics.image_area_ratio > 0.7:
        return ParseStrategy.FULL_OCR

    if text_quality < 0.7:
        return ParseStrategy.FULL_OCR

    if metrics.text_length > 50 and metrics.image_area_ratio > 0.3:
        return ParseStrategy.REGION_OCR

    return ParseStrategy.NATIVE

