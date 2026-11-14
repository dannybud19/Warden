import base64

from app.agents.companies_house.ch_client import CompaniesHouseClient, basic_auth_header
from app.agents.companies_house.models import Outcome, QueryBudget
from app.agents.companies_house.testing import Router, no_sleep
from app.agents.companies_house.web import web_search
from app.core.search import FakeSearch, SearchResult


def test_basic_auth_header_is_key_with_empty_password() -> None:
    assert basic_auth_header("test-key") == "Basic " + base64.b64encode(b"test-key:").decode()


def _company(number: str = "09123456") -> dict:
    return {
        "company_name": "LARKFIELD & CO LETTINGS LTD",
        "company_number": number,
        "company_status": "active",
        "date_of_creation": "2014-07-03",
        "sic_codes": ["68310"],
    }


async def test_client_sends_basic_auth_and_parses(make_ctx) -> None:
    router = Router({("GET", "/company/09123456"): (200, _company())})
    client = CompaniesHouseClient(await make_ctx(router), sleep=no_sleep)
    result = await client.get_company("9123456")  # padded to 8 digits
    assert result.outcome == Outcome.OK and result.value is not None
    assert result.value.company_name == "LARKFIELD & CO LETTINGS LTD"
    assert str(result.value.date_of_creation) == "2014-07-03"
    assert router.requests[0].headers["authorization"] == basic_auth_header("test-key")
    assert router.requests[0].url.host == "api.company-information.service.gov.uk"


async def test_client_404_is_not_found_and_500_is_failed(make_ctx) -> None:
    router = Router(
        {("GET", "/company/99999999"): (404, ""), ("GET", "/company/11111111"): (500, "")}
    )
    client = CompaniesHouseClient(await make_ctx(router), sleep=no_sleep)
    assert (await client.get_company("99999999")).outcome == Outcome.NOT_FOUND
    failed = await client.get_company("11111111")
    assert failed.outcome == Outcome.FAILED
    assert len(router.calls("/company/11111111")) == 3


async def test_client_search_404_and_empty_both_mean_zero_hits(make_ctx) -> None:
    for reply in [(404, ""), (200, {"items": []})]:
        router = Router({("GET", "/search/companies"): reply})
        client = CompaniesHouseClient(await make_ctx(router), sleep=no_sleep)
        result = await client.search_companies("Nothing Ltd")
        assert result.outcome == Outcome.OK and result.value == []


async def test_client_search_uses_company_type_and_ignores_unknown_fields(make_ctx) -> None:
    hit = {
        "title": "PRIME CITY LETTINGS LTD",
        "company_number": "11223344",
        "company_status": "dissolved",
        "company_type": "ltd",
        "date_of_creation": "2018-02-01",
        "address_snippet": "71-75 Shelton Street",
        "kind": "searchresults#company",
    }
    router = Router({("GET", "/search/companies"): (200, {"items": [hit]})})
    client = CompaniesHouseClient(await make_ctx(router), sleep=no_sleep)
    result = await client.search_companies("Prime City Lettings")
    assert result.value is not None and result.value[0].company_type == "ltd"
    assert router.requests[0].url.params["items_per_page"] == "20"


async def test_officers_active_and_completeness(make_ctx) -> None:
    body = {
        "active_count": 3,
        "total_results": 4,
        "items": [
            {"name": "CLARKE, Hannah Louise", "officer_role": "director"},
            {"name": "BROWN, Tom", "officer_role": "director", "resigned_on": "2019-03-01"},
        ],
    }
    router = Router({("GET", "/company/09123456/officers"): (200, body)})
    client = CompaniesHouseClient(await make_ctx(router), sleep=no_sleep)
    result = await client.get_officers("09123456")
    assert result.value is not None
    assert [o.name for o in result.value.active] == ["CLARKE, Hannah Louise"]
    assert not result.value.complete  # active_count 3 but only 1 active fetched


async def test_router_longest_prefix_sequence_and_unmatched_404(make_ctx) -> None:
    router = Router(
        {
            ("GET", "/a"): (200, {"which": "short"}),
            ("GET", "/a/b"): [(500, ""), (200, {"which": "long"})],
        }
    )
    ctx = await make_ctx(router)
    assert (await ctx.http.get("https://x.test/a/b")).status_code == 500
    assert (await ctx.http.get("https://x.test/a/b")).json() == {"which": "long"}
    assert (await ctx.http.get("https://x.test/a/b")).json() == {"which": "long"}  # last repeats
    assert (await ctx.http.get("https://x.test/a/c")).json() == {"which": "short"}
    assert (await ctx.http.get("https://x.test/zzz")).status_code == 404
    assert len(router.calls("/a/b")) == 3


async def test_web_search_budget_and_failure(make_ctx) -> None:
    search = FakeSearch({"q": [SearchResult(title="t", url="https://u.test", snippet="s")]})
    ctx = await make_ctx(search=search)
    budget = QueryBudget(limit=1)
    ok = await web_search(ctx, budget, "q one", sleep=no_sleep)
    assert ok.outcome == Outcome.OK and ok.value is not None and ok.value[0].url == "https://u.test"
    spent = await web_search(ctx, budget, "q two", sleep=no_sleep)
    assert spent.outcome == Outcome.FAILED and spent.error == "query budget"
    assert search.queries == ["q one"]


async def test_web_search_failure_is_failed_not_empty(make_ctx) -> None:
    class Down(FakeSearch):
        async def search(self, query, *, depth="standard"):  # type: ignore[override]
            raise RuntimeError("linkup down")

    ctx = await make_ctx(search=Down())
    result = await web_search(ctx, QueryBudget(), "q", sleep=no_sleep)
    assert result.outcome == Outcome.FAILED
    assert result.error is not None and "3 attempts" in result.error
