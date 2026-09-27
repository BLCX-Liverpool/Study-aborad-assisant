from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deepdoc-lib in an isolated Python runtime.")
    parser.add_argument("--status", action="store_true", help="Check whether deepdoc-lib can be imported.")
    parser.add_argument("--source", type=Path, help="Document path to parse.")
    args = parser.parse_args()

    try:
        if args.status:
            payload = _check_status()
        elif args.source:
            payload = {"status": "ok", "results": _parse_document(args.source)}
        else:
            payload = {"status": "error", "message": "Either --status or --source is required."}
    except Exception as exc:
        payload = {"status": "error", "message": f"{type(exc).__name__}: {exc}"}

    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("status") == "ok" else 1


def _check_status() -> dict[str, Any]:
    import deepdoc  # type: ignore[import-not-found]
    from deepdoc import DocxParser, ExcelParser, HtmlParser, PdfParser  # noqa: F401

    return {
        "status": "ok",
        "package": "deepdoc-lib",
        "version": getattr(deepdoc, "__version__", None),
        "parsers": ["PdfParser", "DocxParser", "ExcelParser", "HtmlParser"],
    }


def _parse_document(source_path: Path) -> list[dict[str, Any]]:
    if not source_path.exists():
        raise FileNotFoundError(str(source_path))

    suffix = source_path.suffix.lower()
    if suffix == ".pdf":
        from deepdoc import PdfParser

        raw_result = PdfParser()(str(source_path), need_image=False, return_html=False)
        return _normalize_pdf_result(raw_result)
    if suffix in {".docx", ".doc"}:
        from deepdoc import DocxParser

        raw_result = DocxParser()(str(source_path))
        return _normalize_docx_result(raw_result)
    if suffix in {".xlsx", ".xls", ".csv"}:
        from deepdoc import ExcelParser

        raw_result = ExcelParser()(str(source_path))
        return _normalize_sequence(raw_result)
    if suffix in {".html", ".htm"}:
        from deepdoc import HtmlParser

        raw_result = HtmlParser()(str(source_path))
        return _normalize_sequence(raw_result)

    raise RuntimeError(f"Unsupported DeepDoc file type: {suffix or '<none>'}")


def _normalize_pdf_result(raw_result: Any) -> list[dict[str, Any]]:
    boxes: Any = raw_result
    tables: Any = []
    if isinstance(raw_result, tuple) and raw_result:
        boxes = raw_result[0]
        tables = raw_result[1] if len(raw_result) > 1 else []

    results: list[dict[str, Any]] = []
    for index, box in enumerate(boxes if isinstance(boxes, list) else []):
        if not isinstance(box, dict):
            continue
        text = str(box.get("text") or box.get("txt") or "").strip()
        if not text:
            continue
        metadata = {
            key: _json_safe(value)
            for key, value in box.items()
            if key not in {"text", "txt", "page_number", "page"} and _is_simple(value)
        }
        results.append(
            {
                "page": _coerce_page(box.get("page_number") or box.get("page")),
                "text": text,
                "confidence": 0.85,
                "metadata": {"ocr_engine": "deepdoc", "parser": "PdfParser", "result_index": index, **metadata},
            }
        )

    for table_index, text in enumerate(_flatten_text(tables)):
        results.append(
            {
                "page": None,
                "text": text,
                "confidence": 0.8,
                "metadata": {"ocr_engine": "deepdoc", "parser": "PdfParser", "kind": "table", "table_index": table_index},
            }
        )
    return results


def _normalize_docx_result(raw_result: Any) -> list[dict[str, Any]]:
    sections: Any = raw_result
    tables: Any = []
    if isinstance(raw_result, tuple) and raw_result:
        sections = raw_result[0]
        tables = raw_result[1] if len(raw_result) > 1 else []

    results: list[dict[str, Any]] = []
    for index, section in enumerate(sections if isinstance(sections, list) else []):
        text = ""
        style = None
        if isinstance(section, tuple):
            text = str(section[0]).strip() if section else ""
            style = str(section[1]).strip() if len(section) > 1 and section[1] else None
        else:
            text = str(section).strip()
        if not text:
            continue
        metadata = {"ocr_engine": "deepdoc", "parser": "DocxParser", "result_index": index}
        if style:
            metadata["style"] = style
        results.append({"page": None, "text": text, "confidence": 0.85, "metadata": metadata})

    for table_index, text in enumerate(_flatten_text(tables)):
        results.append(
            {
                "page": None,
                "text": text,
                "confidence": 0.8,
                "metadata": {"ocr_engine": "deepdoc", "parser": "DocxParser", "kind": "table", "table_index": table_index},
            }
        )
    return results


def _normalize_sequence(raw_result: Any) -> list[dict[str, Any]]:
    return [
        {
            "page": None,
            "text": text,
            "confidence": 0.8,
            "metadata": {"ocr_engine": "deepdoc", "result_index": index},
        }
        for index, text in enumerate(_flatten_text(raw_result))
    ]


def _flatten_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        text = str(value.get("text") or value.get("content") or "").strip()
        return [text] if text else []
    if isinstance(value, tuple | list):
        texts: list[str] = []
        if value and isinstance(value[0], str):
            text = value[0].strip()
            if text:
                texts.append(text)
        else:
            for item in value:
                texts.extend(_flatten_text(item))
        return texts
    return []


def _coerce_page(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_simple(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _json_safe(value: Any) -> Any:
    if _is_simple(value):
        return value
    return str(value)


if __name__ == "__main__":
    sys.exit(main())
