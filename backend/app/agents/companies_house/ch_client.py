"""Thin Companies House wrapper over `ctx.http` (plan App. B). Never builds its own client."""

import asyncio
import base64
from typing import Any

from pydantic import ValidationError

from app.agents.companies_house.constants import (
    CH_BASE_URL,
    CH_TIMEOUT_S,
    OFFICERS_PAGE_SIZE,
    SEARCH_PAGE_SIZE,
)
from app.agents.companies_house.models import (
    CompanyProfile,
    DisqualifiedHit,
    Fetch,
    OfficerList,
    Outcome,
    SearchHit,
)
from app.agents.companies_house.normalise import normalise_number
from app.agents.companies_house.retry import Sleep
from app.agents.companies_house.web import http_get
from app.core.agent import AgentContext


def basic_auth_header(api_key: str) -> str:
    """HTTP basic auth with the API key as username and an empty password."""
    return "Basic " + base64.b64encode(f"{api_key}:".encode()).decode()


class CompaniesHouseClient:
    def __init__(self, ctx: AgentContext, *, sleep: Sleep = asyncio.sleep) -> None:
        self._ctx = ctx
        self._sleep = sleep
        self._headers = {"Authorization": basic_auth_header(ctx.settings.companies_house_api_key)}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Fetch[Any]:
        """GET `path` and parse the JSON body. An unparseable body is a failure, not a 404."""
        result = await http_get(
            self._ctx,
            f"{CH_BASE_URL}{path}",
            per_try_timeout=CH_TIMEOUT_S,
            headers=self._headers,
            params=params,
            sleep=self._sleep,
        )
        if result.outcome != Outcome.OK or result.value is None:
            return Fetch(
                result.outcome, error=result.error, url=result.url, status_code=result.status_code
            )
        try:
            body = result.value.json()
        except ValueError:
            return Fetch(Outcome.FAILED, error="invalid JSON", url=result.url)
        return Fetch(Outcome.OK, body, url=result.url, status_code=result.status_code)

    @staticmethod
    def _failed(raw: Fetch[Any], error: str) -> Fetch[Any]:
        return Fetch(Outcome.FAILED, error=error, url=raw.url)

    async def get_company(self, number: str) -> Fetch[CompanyProfile]:
        """`GET /company/{n}`. NOT_FOUND means the number really is not on the register."""
        raw = await self._get(f"/company/{normalise_number(number)}")
        if raw.outcome != Outcome.OK:
            return Fetch(raw.outcome, error=raw.error, url=raw.url, status_code=raw.status_code)
        try:
            return Fetch(Outcome.OK, CompanyProfile.model_validate(raw.value), url=raw.url)
        except ValidationError as exc:
            return self._failed(raw, f"unexpected company payload: {exc.error_count()} errors")

    async def search_companies(self, name: str) -> Fetch[list[SearchHit]]:
        """`GET /search/companies`. A 404 or `items: []` both mean zero hits (OK, empty list)."""
        raw = await self._get("/search/companies", {"q": name, "items_per_page": SEARCH_PAGE_SIZE})
        if raw.outcome == Outcome.NOT_FOUND:
            return Fetch(Outcome.OK, [], url=raw.url, status_code=404)
        if raw.outcome != Outcome.OK:
            return Fetch(raw.outcome, error=raw.error, url=raw.url, status_code=raw.status_code)
        try:
            items = (raw.value or {}).get("items") or []
            return Fetch(Outcome.OK, [SearchHit.model_validate(i) for i in items], url=raw.url)
        except (ValidationError, AttributeError, TypeError):
            return self._failed(raw, "unexpected search payload")

    async def get_officers(self, number: str) -> Fetch[OfficerList]:
        """`GET /company/{n}/officers` (first page of 100; use `OfficerList.complete`)."""
        raw = await self._get(
            f"/company/{normalise_number(number)}/officers",
            {"items_per_page": OFFICERS_PAGE_SIZE},
        )
        if raw.outcome != Outcome.OK:
            return Fetch(raw.outcome, error=raw.error, url=raw.url, status_code=raw.status_code)
        try:
            return Fetch(Outcome.OK, OfficerList.model_validate(raw.value), url=raw.url)
        except ValidationError:
            return self._failed(raw, "unexpected officers payload")

    async def search_disqualified(self, query: str) -> Fetch[list[DisqualifiedHit]]:
        """`GET /search/disqualified-officers`. 404 or no items means zero hits."""
        raw = await self._get("/search/disqualified-officers", {"q": query})
        if raw.outcome == Outcome.NOT_FOUND:
            return Fetch(Outcome.OK, [], url=raw.url, status_code=404)
        if raw.outcome != Outcome.OK:
            return Fetch(raw.outcome, error=raw.error, url=raw.url, status_code=raw.status_code)
        try:
            items = (raw.value or {}).get("items") or []
            return Fetch(
                Outcome.OK, [DisqualifiedHit.model_validate(i) for i in items], url=raw.url
            )
        except (ValidationError, AttributeError, TypeError):
            return self._failed(raw, "unexpected disqualified payload")
