"""Live web search protocol, the Linkup adapter and a fake for tests."""

from typing import Literal, Protocol

import httpx
from pydantic import BaseModel

from app.core.settings import Settings


class SearchResult(BaseModel):
    """One web hit. Agents MUST cite `url` in `EvidenceRef.quote` or `Finding.detail`."""

    title: str
    url: str
    snippet: str


class WebSearchClient(Protocol):
    async def search(
        self, query: str, *, depth: Literal["standard", "deep"] = "standard"
    ) -> list[SearchResult]: ...


class LinkupSearch:
    """Linkup search API adapter. Not exercised in tests (no network)."""

    URL = "https://api.linkup.so/v1/search"

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._key = settings.linkup_api_key
        self._http = http

    async def search(
        self, query: str, *, depth: Literal["standard", "deep"] = "standard"
    ) -> list[SearchResult]:
        """Run one search and map Linkup results to `SearchResult`."""
        response = await self._http.post(
            self.URL,
            headers={"Authorization": f"Bearer {self._key}"},
            json={"q": query, "depth": depth, "outputType": "searchResults"},
        )
        response.raise_for_status()
        return [
            SearchResult(
                title=item.get("name", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
            )
            for item in response.json().get("results", [])
        ]


class FakeSearch:
    """Canned search for tests: substring match on the query, else no results."""

    def __init__(self, results: dict[str, list[SearchResult]] | None = None) -> None:
        self.results = results or {}
        self.queries: list[str] = []

    async def search(
        self, query: str, *, depth: Literal["standard", "deep"] = "standard"
    ) -> list[SearchResult]:
        self.queries.append(query)
        for key, value in self.results.items():
            if key in query:
                return value
        return []
