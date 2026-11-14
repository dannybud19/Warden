"""Fixtures for the companies_house tests (case fixtures come from backend/conftest.py)."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack

import httpx
import pytest

from app.agents.companies_house.testing import Router
from app.core.agent import AgentContext
from app.core.llm import FakeLLM, LLMClient
from app.core.logging import get_logger
from app.core.search import FakeSearch, WebSearchClient
from app.core.settings import Settings

MakeCtx = Callable[..., Awaitable[AgentContext]]


@pytest.fixture
def ch_settings() -> Settings:
    """Settings with a Companies House key so the agent's key check passes; ignores any .env."""
    return Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        default_agent_mode="stub",
        storage="memory",
        companies_house_api_key="test-key",
        linkup_api_key="test-linkup",
        anthropic_api_key="test-anthropic",
    )


@pytest.fixture
async def make_ctx(ch_settings: Settings) -> AsyncIterator[MakeCtx]:
    """Factory: `ctx = await make_ctx(router_or_routes, search=..., llm=...)`.

    The HTTP client is backed by a Router (404 for everything unmatched). Pass a Router you keep
    a reference to when you want to assert on `router.requests`.
    """
    stack = AsyncExitStack()

    async def _make(
        routes: Router | dict | None = None,
        *,
        search: WebSearchClient | None = None,
        llm: LLMClient | None = None,
        settings: Settings | None = None,
    ) -> AgentContext:
        router = routes if isinstance(routes, Router) else Router(routes)
        http = await stack.enter_async_context(
            httpx.AsyncClient(transport=httpx.MockTransport(router))
        )
        return AgentContext(
            llm=llm or FakeLLM(),
            search=search or FakeSearch(),
            http=http,
            settings=settings or ch_settings,
            log=get_logger("test"),
        )

    try:
        yield _make
    finally:
        await stack.aclose()
