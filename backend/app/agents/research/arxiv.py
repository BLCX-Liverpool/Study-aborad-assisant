import xml.etree.ElementTree as ET

import httpx

from app.schemas.research import ArxivSearchRequest, ArxivSearchResponse, ResearchSource

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"


class ArxivSearchClient:
    def __init__(self, base_url: str = ARXIV_API_URL, timeout: float = 15.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    async def search(self, request: ArxivSearchRequest) -> ArxivSearchResponse:
        params = {
            "search_query": f"all:{request.query}",
            "start": 0,
            "max_results": request.max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()
        return ArxivSearchResponse(
            query=request.query,
            sources=parse_arxiv_atom(response.text),
        )


def parse_arxiv_atom(xml_text: str) -> list[ResearchSource]:
    root = ET.fromstring(xml_text)
    sources: list[ResearchSource] = []
    for entry in root.findall(f"{ATOM}entry"):
        title = _text(entry, "title")
        summary = _text(entry, "summary")
        published = _text(entry, "published")
        authors = [_text(author, "name") for author in entry.findall(f"{ATOM}author")]
        url = _entry_url(entry)
        pdf_url = _pdf_url(entry)
        sources.append(
            ResearchSource(
                source_type="arxiv",
                title=" ".join(title.split()),
                url=pdf_url or url,
                summary=" ".join(summary.split()) if summary else None,
                authors=[author for author in authors if author],
                published_at=published,
                metadata={"entry_url": url, "pdf_url": pdf_url},
            )
        )
    return sources


def _text(element: ET.Element, name: str) -> str:
    child = element.find(f"{ATOM}{name}")
    return child.text.strip() if child is not None and child.text else ""


def _entry_url(entry: ET.Element) -> str:
    link = entry.find(f"{ATOM}id")
    return link.text.strip() if link is not None and link.text else ""


def _pdf_url(entry: ET.Element) -> str | None:
    for link in entry.findall(f"{ATOM}link"):
        if link.attrib.get("title") == "pdf":
            return link.attrib.get("href")
    return None
