"""Builds the AgentContext: real clients when keys are set, fakes otherwise."""

import httpx

from app.core.agent import AgentContext
from app.core.llm import AnthropicLLM, FakeLLM, LLMClient
from app.core.logging import get_logger
from app.core.search import FakeSearch, LinkupSearch, WebSearchClient
from app.core.settings import Settings


def build_context(settings: Settings) -> AgentContext:
    """Real LLM/search clients when their keys are set, `FakeLLM`/`FakeSearch` otherwise."""
    log = get_logger()
    http = httpx.AsyncClient(timeout=30.0)

    llm: LLMClient
    if settings.anthropic_api_key:
        llm = AnthropicLLM(settings)
    else:
        log.warning("ANTHROPIC_API_KEY is not set: using FakeLLM")
        llm = FakeLLM()

    search: WebSearchClient
    if settings.linkup_api_key:
        search = LinkupSearch(settings, http)
    else:
        log.warning("LINKUP_API_KEY is not set: using FakeSearch")
        search = FakeSearch()

    return AgentContext(llm=llm, search=search, http=http, settings=settings, log=log)
