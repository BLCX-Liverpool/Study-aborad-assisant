from typing import Protocol

from app.schemas.research import ResearchSource, WebSearchRequest


class WebSearchProvider(Protocol):
    name: str

    async def search(self, request: WebSearchRequest) -> list[ResearchSource]:
        ...


class WebSearchProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, WebSearchProvider] = {}

    def register(self, provider: WebSearchProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> WebSearchProvider | None:
        return self._providers.get(name)

    def first_available(self) -> WebSearchProvider | None:
        return next(iter(self._providers.values()), None)

    def names(self) -> list[str]:
        return sorted(self._providers)
