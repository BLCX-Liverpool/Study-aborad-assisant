import html
import re
from urllib.parse import quote_plus

import httpx

from app.schemas.research import ResearchSource, WebSearchRequest, WebSearchResponse
from app.agents.research.web_providers import WebSearchProviderRegistry


class DuckDuckGoHtmlProvider:
    name = "duckduckgo_html"

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    async def search(self, request: WebSearchRequest) -> list[ResearchSource]:
        url = f"https://duckduckgo.com/html/?q={quote_plus(request.query)}"
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "study-abroad-assistant/0.1"})
            response.raise_for_status()
        return parse_duckduckgo_html(response.text, request.max_results)


class WebSearchClient:
    def __init__(self, registry: WebSearchProviderRegistry | None = None) -> None:
        self.registry = registry or _default_registry()

    async def search(self, request: WebSearchRequest) -> WebSearchResponse:
        assumptions = [f"Used web search provider registry: {', '.join(self.registry.names())}."]
        provider = self.registry.first_available()
        if provider is None:
            return WebSearchResponse(query=request.query, sources=[], assumptions=[*assumptions, "No provider available."])
        try:
            sources = await provider.search(request)
        except Exception as exc:
            return WebSearchResponse(query=request.query, sources=[], assumptions=[*assumptions, f"Web search failed: {exc}"])

        return WebSearchResponse(
            query=request.query,
            sources=sources,
            assumptions=[*assumptions, f"Provider used: {provider.name}"],
        )


def _default_registry() -> WebSearchProviderRegistry:
    registry = WebSearchProviderRegistry()
    registry.register(DuckDuckGoHtmlProvider())
    return registry


def parse_duckduckgo_html(html_text: str, max_results: int) -> list[ResearchSource]:
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    results: list[ResearchSource] = []
    for match in pattern.finditer(html_text):
        title = re.sub(r"<.*?>", "", match.group("title"))
        results.append(
            ResearchSource(
                source_type="web",
                title=html.unescape(" ".join(title.split())),
                url=html.unescape(match.group("url")),
            )
        )
        if len(results) >= max_results:
            break
    return results
