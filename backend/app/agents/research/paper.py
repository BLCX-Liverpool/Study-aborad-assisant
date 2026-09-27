from pathlib import Path
import hashlib
from urllib.parse import urlparse

import httpx

from app.schemas.research import PaperDownloadRequest, PaperDownloadResponse


class PaperRetrievalClient:
    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    async def download(self, request: PaperDownloadRequest) -> PaperDownloadResponse:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        filename = request.filename or _filename_from_url(request.url)
        output_path = request.output_dir / filename

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(request.url)
            response.raise_for_status()

        digest = hashlib.sha256(response.content).hexdigest()
        duplicate = _find_duplicate(request.output_dir, digest, output_path)
        output_path.write_bytes(response.content)
        summary = _summarize_pdf(output_path)
        return PaperDownloadResponse(
            url=request.url,
            local_path=output_path,
            content_type=response.headers.get("content-type"),
            bytes_written=len(response.content),
            sha256=digest,
            duplicate_of=duplicate,
            title=_title_from_headers_or_filename(response.headers, output_path),
            summary=summary,
            metadata={
                "etag": response.headers.get("etag"),
                "last_modified": response.headers.get("last-modified"),
                "duplicate_detected": duplicate is not None,
            },
        )


def _filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name or "paper.pdf"
    if "." not in name:
        name = f"{name}.pdf"
    return name


def _find_duplicate(output_dir: Path, digest: str, target: Path) -> Path | None:
    for path in output_dir.glob("*"):
        if path == target or not path.is_file():
            continue
        try:
            if hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                return path
        except OSError:
            continue
    return None


def _summarize_pdf(path: Path, max_chars: int = 600) -> str | None:
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        with pdfplumber.open(path) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages[:2])
    except Exception:
        return None
    text = " ".join(text.split())
    return text[:max_chars] if text else None


def _title_from_headers_or_filename(headers, path: Path) -> str:
    disposition = headers.get("content-disposition", "")
    if "filename=" in disposition:
        return disposition.split("filename=", 1)[1].strip('" ')
    return path.stem.replace("_", " ").replace("-", " ").strip() or path.name
