import json
import os
from pathlib import Path
import subprocess
from typing import Protocol

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.documents.models import DocumentContentType, ParsedDocument, ParsedDocumentElement, ParseStrategy


class OcrPageResult(BaseModel):
    page: int | None = None
    text: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: dict = Field(default_factory=dict)


class OcrEngine(Protocol):
    def extract(self, source_path: Path) -> list[OcrPageResult]:
        ...


class DeepdocOcrEngine:
    """DeepDoc adapter that runs deepdoc-lib in an isolated Python process."""

    def extract(self, source_path: Path) -> list[OcrPageResult]:
        status = check_deepdoc_runtime()
        if not status.available:
            raise RuntimeError(status.message)

        raw_result = _run_deepdoc_subprocess(["--source", str(source_path)])
        return _normalize_deepdoc_result(raw_result)


class RapidOcrEngine:
    def extract(self, source_path: Path) -> list[OcrPageResult]:
        status = check_rapidocr_runtime()
        if not status.available:
            raise RuntimeError(status.message)

        source_path = Path(source_path)
        if source_path.suffix.lower() == ".pdf":
            return self._extract_pdf(source_path)
        return self._extract_image(source_path, page=None)

    def _extract_pdf(self, source_path: Path) -> list[OcrPageResult]:
        import pypdfium2 as pdfium

        settings = get_settings()
        document = pdfium.PdfDocument(source_path)
        results: list[OcrPageResult] = []
        max_pages = min(len(document), settings.ocr_max_pages)
        for page_index in range(max_pages):
            page = document[page_index]
            bitmap = page.render(scale=settings.ocr_pdf_render_scale).to_pil()
            results.extend(self._extract_pil_image(bitmap, page=page_index + 1))
        return results

    def _extract_image(self, source_path: Path, page: int | None) -> list[OcrPageResult]:
        from PIL import Image

        with Image.open(source_path) as image:
            return self._extract_pil_image(image, page=page)

    def _extract_pil_image(self, image, page: int | None) -> list[OcrPageResult]:
        import numpy as np
        from rapidocr import RapidOCR

        engine = RapidOCR()
        result = engine(np.array(image.convert("RGB")))
        return _normalize_rapidocr_result(result, page=page)


class ConfiguredOcrEngine:
    def extract(self, source_path: Path) -> list[OcrPageResult]:
        settings = get_settings()
        engine_name = settings.ocr_engine.lower()
        if engine_name == "deepdoc":
            return DeepdocOcrEngine().extract(source_path)
        if engine_name == "rapidocr":
            return RapidOcrEngine().extract(source_path)
        if engine_name != "auto":
            raise RuntimeError(f"Unsupported OCR_ENGINE {settings.ocr_engine!r}. Use auto, deepdoc, or rapidocr.")

        deepdoc_status = check_deepdoc_runtime()
        if deepdoc_status.available:
            return DeepdocOcrEngine().extract(source_path)

        rapidocr_status = check_rapidocr_runtime()
        if rapidocr_status.available:
            return RapidOcrEngine().extract(source_path)

        raise RuntimeError(
            "No OCR runtime is available. "
            f"Deepdoc: {deepdoc_status.message}; RapidOCR: {rapidocr_status.message}"
        )


class DeepdocRuntimeStatus(BaseModel):
    available: bool
    package: str = "ocr"
    message: str
    configured_engine: str = "auto"
    deepdoc_available: bool = False
    rapidocr_available: bool = False
    active_engine: str | None = None
    metadata: dict = Field(default_factory=dict)


def check_deepdoc_runtime() -> DeepdocRuntimeStatus:
    settings = get_settings()
    deepdoc_python = _resolve_deepdoc_python(settings.deepdoc_python)
    if not deepdoc_python.exists():
        return DeepdocRuntimeStatus(
            available=False,
            package="deepdoc",
            message=f"DeepDoc subprocess Python was not found: {deepdoc_python}",
            configured_engine=settings.ocr_engine,
            deepdoc_available=False,
        )
    try:
        payload = _run_deepdoc_subprocess(["--status"])
    except RuntimeError as exc:
        return DeepdocRuntimeStatus(
            available=False,
            package="deepdoc",
            message=str(exc),
            configured_engine=settings.ocr_engine,
            deepdoc_available=False,
        )
    return DeepdocRuntimeStatus(
        available=True,
        package="deepdoc",
        message=f"DeepDoc subprocess runtime is available via {deepdoc_python}.",
        configured_engine=settings.ocr_engine,
        deepdoc_available=True,
        active_engine="deepdoc",
        metadata={
            "runtime": "subprocess",
            "python": str(deepdoc_python),
            "deepdoc_package": payload.get("package"),
            "version": payload.get("version"),
            "parsers": payload.get("parsers", []),
        },
    )


def check_rapidocr_runtime() -> DeepdocRuntimeStatus:
    settings = get_settings()
    try:
        import onnxruntime  # noqa: F401
        import pypdfium2  # noqa: F401
        import PIL  # noqa: F401
    except ImportError as exc:
        return DeepdocRuntimeStatus(
            available=False,
            package="rapidocr",
            message=f"RapidOCR support dependency is missing: {exc}",
            configured_engine=settings.ocr_engine,
        )
    try:
        from rapidocr import RapidOCR
    except ImportError:
        return DeepdocRuntimeStatus(
            available=False,
            package="rapidocr",
            message="RapidOCR is not installed or not importable.",
            configured_engine=settings.ocr_engine,
        )
    try:
        RapidOCR()
    except Exception as exc:
        return DeepdocRuntimeStatus(
            available=False,
            package="rapidocr",
            message=f"RapidOCR failed to initialize: {exc}",
            configured_engine=settings.ocr_engine,
        )
    return DeepdocRuntimeStatus(
        available=True,
        package="rapidocr",
        message="RapidOCR runtime is available.",
        configured_engine=settings.ocr_engine,
        rapidocr_available=True,
        active_engine="rapidocr",
    )


def check_ocr_runtime() -> DeepdocRuntimeStatus:
    settings = get_settings()
    engine_name = settings.ocr_engine.lower()
    if engine_name == "deepdoc":
        deepdoc_status = check_deepdoc_runtime()
        return DeepdocRuntimeStatus(
            available=deepdoc_status.available,
            package="ocr",
            message=deepdoc_status.message,
            configured_engine=settings.ocr_engine,
            deepdoc_available=deepdoc_status.available,
            rapidocr_available=False,
            active_engine="deepdoc" if deepdoc_status.available else None,
            metadata=deepdoc_status.metadata,
        )
    if engine_name == "rapidocr":
        rapidocr_status = check_rapidocr_runtime()
        return DeepdocRuntimeStatus(
            available=rapidocr_status.available,
            package="ocr",
            message=rapidocr_status.message,
            configured_engine=settings.ocr_engine,
            deepdoc_available=False,
            rapidocr_available=rapidocr_status.available,
            active_engine="rapidocr" if rapidocr_status.available else None,
            metadata=rapidocr_status.metadata,
        )
    if engine_name == "auto":
        deepdoc_status = check_deepdoc_runtime()
        if deepdoc_status.available:
            return DeepdocRuntimeStatus(
                available=True,
                package="ocr",
                message="OCR runtime is available through Deepdoc.",
                configured_engine=settings.ocr_engine,
                deepdoc_available=True,
                rapidocr_available=False,
                active_engine="deepdoc",
                metadata=deepdoc_status.metadata,
            )
        rapidocr_status = check_rapidocr_runtime()
        if rapidocr_status.available:
            return DeepdocRuntimeStatus(
                available=True,
                package="ocr",
                message="OCR runtime is available through RapidOCR fallback.",
                configured_engine=settings.ocr_engine,
                deepdoc_available=False,
                rapidocr_available=True,
                active_engine="rapidocr",
                metadata=rapidocr_status.metadata,
            )
        message = f"No OCR runtime is available. Deepdoc: {deepdoc_status.message}; RapidOCR: {rapidocr_status.message}"
        return DeepdocRuntimeStatus(
            available=False,
            package="ocr",
            message=message,
            configured_engine=settings.ocr_engine,
            deepdoc_available=False,
            rapidocr_available=False,
        )
    return DeepdocRuntimeStatus(
        available=False,
        package="ocr",
        message=f"Unsupported OCR_ENGINE {settings.ocr_engine!r}. Use auto, deepdoc, or rapidocr.",
        configured_engine=settings.ocr_engine,
    )


class OcrDocumentProcessor:
    def __init__(self, engine: OcrEngine) -> None:
        self.engine = engine

    def apply_ocr_if_needed(self, parsed: ParsedDocument) -> ParsedDocument:
        if not _needs_ocr(parsed):
            return parsed

        results = self.engine.extract(parsed.source_path)
        if not results:
            return parsed.model_copy(
                update={
                    "metadata": {
                        **parsed.metadata,
                        "ocr": {"status": "no_text_returned", "engine": "configured"},
                    }
                }
            )

        elements = list(parsed.elements)
        engine_name = results[0].metadata.get("ocr_engine", "configured") if results else "configured"
        for index, result in enumerate(results):
            elements.append(
                ParsedDocumentElement(
                    content_type=DocumentContentType.PARAGRAPH,
                    text=result.text,
                    page=result.page,
                    parse_strategy=ParseStrategy.FULL_OCR,
                    text_quality_score=result.confidence,
                    source_metadata={
                        "ocr_engine": engine_name,
                        "ocr_result_index": index,
                        **result.metadata,
                    },
                )
            )

        return parsed.model_copy(
            update={
                "elements": elements,
                "metadata": {
                    **parsed.metadata,
                    "ocr": {"status": "applied", "engine": engine_name, "pages": len(results)},
                },
            }
        )


def _needs_ocr(parsed: ParsedDocument) -> bool:
    strategy = parsed.metadata.get("parse_strategy")
    if strategy in {ParseStrategy.FULL_OCR.value, ParseStrategy.REGION_OCR.value}:
        return True
    return any(element.parse_strategy in {ParseStrategy.FULL_OCR, ParseStrategy.REGION_OCR} for element in parsed.elements)


def _run_deepdoc_subprocess(arguments: list[str]) -> dict:
    settings = get_settings()
    command = [str(_resolve_deepdoc_python(settings.deepdoc_python)), str(_deepdoc_runner_path()), *arguments]
    env = os.environ.copy()
    if settings.deepdoc_model_home:
        env["DEEPDOC_MODEL_HOME"] = str(settings.deepdoc_model_home)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            env=env,
            text=True,
            timeout=settings.deepdoc_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"DeepDoc subprocess timed out after {settings.deepdoc_timeout_seconds}s.") from exc
    except OSError as exc:
        raise RuntimeError(f"DeepDoc subprocess failed to start: {exc}") from exc

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError as exc:
        details = stderr or stdout or "<empty output>"
        raise RuntimeError(f"DeepDoc subprocess returned non-JSON output: {details}") from exc

    if completed.returncode != 0 or payload.get("status") == "error":
        message = str(payload.get("message") or stderr or "DeepDoc subprocess failed.")
        raise RuntimeError(message)
    return payload


def _deepdoc_runner_path() -> Path:
    return Path(__file__).with_name("deepdoc_subprocess_runner.py")


def _resolve_deepdoc_python(configured_path: Path) -> Path:
    if configured_path.is_absolute():
        return configured_path
    return Path.cwd() / configured_path


def _normalize_deepdoc_result(raw_result) -> list[OcrPageResult]:
    if isinstance(raw_result, dict) and "results" in raw_result:
        return [OcrPageResult.model_validate(item) for item in raw_result.get("results", [])]
    if isinstance(raw_result, str):
        return [OcrPageResult(text=raw_result, confidence=0.7, metadata={"ocr_engine": "deepdoc"})]
    if isinstance(raw_result, list):
        normalized: list[OcrPageResult] = []
        for item in raw_result:
            if isinstance(item, str):
                normalized.append(OcrPageResult(text=item, confidence=0.7, metadata={"ocr_engine": "deepdoc"}))
            elif isinstance(item, dict):
                normalized.append(
                    OcrPageResult(
                        page=item.get("page"),
                        text=str(item.get("text", "")),
                        confidence=float(item.get("confidence", 0.7)),
                        metadata={
                            "ocr_engine": "deepdoc",
                            **{key: value for key, value in item.items() if key not in {"page", "text", "confidence"}},
                        },
                    )
                )
        return [item for item in normalized if item.text.strip()]
    raise RuntimeError("Unsupported Deepdoc OCR result format.")


def _normalize_rapidocr_result(raw_result, page: int | None) -> list[OcrPageResult]:
    txts = getattr(raw_result, "txts", None)
    scores = getattr(raw_result, "scores", None)
    if txts is None:
        return []
    normalized = []
    for index, text in enumerate(txts):
        cleaned = str(text).strip()
        if not cleaned:
            continue
        score = 0.7
        if scores is not None and index < len(scores):
            score = float(scores[index])
        normalized.append(
            OcrPageResult(
                page=page,
                text=cleaned,
                confidence=max(0.0, min(score, 1.0)),
                metadata={"ocr_engine": "rapidocr", "line_index": index},
            )
        )
    return normalized
