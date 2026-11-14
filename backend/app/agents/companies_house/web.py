"""Shared I/O helpers: one HTTP GET and one Linkup search, both with retries and a budget."""

import asyncio
from typing import Any, Literal

import httpx

from app.agents.companies_house.constants import (
    LINKUP_DEEP_TIMEOUT_S,
    LINKUP_STANDARD_TIMEOUT_S,
)
from app.agents.companies_house.models import Fetch, Outcome, QueryBudget
from app.agents.companies_house.retry import Sleep, with_retries
from app.core.agent import AgentContext
from app.core.search import SearchResult


async def http_get(
    ctx: AgentContext,
    url: str,
    *,
    per_try_timeout: float,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    follow_redirects: bool = False,
    sleep: Sleep = asyncio.sleep,
) -> Fetch[httpx.Response]:
    """GET through `ctx.http` with retries. `url` in the result includes the query string."""
    request = ctx.http.build_request("GET", url, headers=headers, params=params)
    full_url = str(request.url)

    async def call() -> httpx.Response:
        return await ctx.http.get(
            url, headers=headers, params=params, follow_redirects=follow_redirects
        )

    result = await with_retries(call, per_try_timeout=per_try_timeout, sleep=sleep, url=full_url)
    if result.outcome == Outcome.FAILED:
        # 401/403 means a key or config problem: say so clearly in the log.
        level = "error" if result.status_code in (401, 403) else "warning"
        getattr(ctx.log, level)("companies_house: GET %s failed: %s", full_url, result.error)
    return result


async def web_search(
    ctx: AgentContext,
    budget: QueryBudget,
    query: str,
    *,
    depth: Literal["standard", "deep"] = "standard",
    sleep: Sleep = asyncio.sleep,
) -> Fetch[list[SearchResult]]:
    """One Linkup query through `ctx.search` with retries, counted against `budget`.

    Budget exhausted gives FAILED with error "query budget" (never 'no results'). A 404 from the
    search service is also a failure here, not an empty result.
    """
    if not budget.take():
        return Fetch(Outcome.FAILED, error="query budget")
    timeout = LINKUP_DEEP_TIMEOUT_S if depth == "deep" else LINKUP_STANDARD_TIMEOUT_S

    async def call() -> list[SearchResult]:
        return await ctx.search.search(query, depth=depth)

    result = await with_retries(call, per_try_timeout=timeout, sleep=sleep)
    if result.outcome == Outcome.NOT_FOUND:
        return Fetch(Outcome.FAILED, error="search service returned 404")
    if result.outcome == Outcome.FAILED:
        ctx.log.warning("companies_house: search %r failed: %s", query, result.error)
    return result
