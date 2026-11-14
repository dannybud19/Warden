"""Reputation module: web reports, redress/CMP clears, Rogue Checker. Offline, no real sleeping."""

import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

from app.agents.companies_house.constants import (
    EV_ROGUE,
    EV_WEB,
    EXTERNAL_EVIDENCE_IDS,
    ROGUE_CHECKER_URL,
)
from app.agents.companies_house.models import (
    Address,
    CompanyProfile,
    ModuleResult,
    QueryBudget,
    ResolvedCompany,
)
from app.agents.companies_house.modules import reputation
from app.agents.companies_house.modules.reputation import (
    parse_rogue_date,
    parse_rogue_page,
    rogue_match,
)
from app.agents.companies_house.normalise import url_hash8
from app.agents.companies_house.testing import TODAY, Router, fixture_json, fixture_text, no_sleep
from app.contracts import Case, EvidenceRef, Finding
from app.core.llm import FakeLLM
from app.core.search import FakeSearch, SearchResult

ROGUE_PATH = urlparse(ROGUE_CHECKER_URL).path
AGENT_DIR = Path(reputation.__file__).parent.parent


def make_company(
    name: str = "PRIME CITY LETTINGS LTD",
    number: str = "10452757",
    supplied: str | None = "Prime City Lettings",
) -> ResolvedCompany:
    profile = CompanyProfile(
        company_name=name,
        company_number=number,
        registered_office_address=Address(
            address_line_1="1 Test Street", locality="London", postal_code="E1 1AA"
        ),
    )
    return ResolvedCompany(
        profile=profile, number=number, matched_by="number", supplied_name=supplied
    )


def larkfield() -> ResolvedCompany:
    return make_company("LARKFIELD & CO LETTINGS LTD", "09123456", "Larkfield Lettings")


def results(name: str) -> list[SearchResult]:
    return [SearchResult(**item) for item in fixture_json("reputation", name)]


def rogue_ok(html: str) -> Router:
    return Router({("GET", ROGUE_PATH): (200, html)})


def rogue_miss() -> Router:
    return rogue_ok(fixture_text("reputation", "rogue_miss.html"))


def verdicts(*items: dict) -> FakeLLM:
    return FakeLLM(default=json.dumps({"items": list(items)}))


def verdict(index: int, label: str, quote: str, *, about: bool = True) -> dict:
    return {
        "index": index,
        "keep": about,
        "label": label,
        "about_this_company": about,
        "quote": quote,
    }


def entry_html(name: str, number: str | None, *, expires: str = "Monday 1 January 2030") -> str:
    return (
        f"<div><h3 data-search-highlight>{name}{f' ({number})' if number else ''}</h3><ul>"
        "<li><strong>Enforcement action type:</strong> Financial penalty</li>"
        "<li><strong>Enforcement authority:</strong> London Borough of Test</li>"
        "<li><strong>Enforcement date:</strong> Monday 2 February 2026</li>"
        f"<li><strong>Record expires:</strong> {expires}</li></ul></div>"
    )


def page_html(entries: list[str]) -> str:
    return "<html><body><main>" + "".join(entries) + "</main></body></html>"


def filler(count: int, start: int = 0) -> list[str]:
    return [
        entry_html(f"Unrelated Agent {i} Limited", f"{20000000 + i}")
        for i in range(start, start + count)
    ]


class DownSearch(FakeSearch):
    """Linkup unreachable."""

    async def search(self, query, *, depth="standard"):  # type: ignore[override]
        self.queries.append(query)
        raise httpx.ConnectError("linkup down")


async def run_rep(
    make_ctx,
    case: Case,
    company: ResolvedCompany,
    *,
    router: Router | None = None,
    search: FakeSearch | None = None,
    llm: FakeLLM | None = None,
    budget: QueryBudget | None = None,
) -> ModuleResult:
    ctx = await make_ctx(router or rogue_miss(), search=search or FakeSearch(), llm=llm)
    return await reputation.run(
        ctx, case, company, budget or QueryBudget(), today=TODAY, sleep=no_sleep
    )


def quote_of(item: Finding | EvidenceRef) -> str:
    """The first quote of a finding, or the quote of one evidence ref."""
    ref = item.evidence[0] if isinstance(item, Finding) else item
    assert ref.quote
    return ref.quote


def by_prefix(result: ModuleResult, prefix: str) -> list[Finding]:
    return [f for f in result.findings if f.id.startswith(f"companies_house:{prefix}")]


# --- scam reports and reviews ---------------------------------------------------------------

SCAM_QUOTE = "the deposit was never returned"


def scam_search() -> FakeSearch:
    return FakeSearch({"scam OR fraud": results("linkup_scam.json")})


async def test_scam_report_about_this_company_is_a_finding_with_its_url(
    make_ctx, genuine_flat_case
) -> None:
    llm = verdicts(verdict(0, "scam_report", SCAM_QUOTE))
    result = await run_rep(
        make_ctx, genuine_flat_case, make_company(), search=scam_search(), llm=llm
    )
    [finding] = by_prefix(result, "scam-report-")
    assert finding.supports == "suspicious" and finding.severity == "high"
    assert finding.confidence == 0.75 and finding.hard_flag is False
    assert finding.check_id == "landlord_identity"
    assert (
        "Source: https://www.example-forum.org/threads/prime-city-lettings-deposit"
        in finding.detail
    )
    assert finding.detail.startswith(f'Someone online reports: "{SCAM_QUOTE}".')
    [ref] = finding.evidence
    assert ref.evidence_id == EV_WEB and ref.quote == SCAM_QUOTE
    assert SCAM_QUOTE in results("linkup_scam.json")[0].snippet
    assert llm.calls[0]["model"] is None and len(llm.calls) == 1


async def test_filter_gets_the_registered_name_not_the_students_spelling(
    make_ctx, genuine_flat_case
) -> None:
    llm = verdicts()
    await run_rep(
        make_ctx,
        genuine_flat_case,
        make_company(supplied="Primecity Lets"),
        search=scam_search(),
        llm=llm,
    )
    system = llm.calls[0]["system"]
    assert "PRIME CITY LETTINGS LTD (Companies House number 10452757)" in system
    assert 'told the name "Primecity Lets"' in system
    assert "1 Test Street, London, E1 1AA" in system


async def test_search_queries_use_the_registered_name_and_expected_depths(
    make_ctx, genuine_flat_case
) -> None:
    search = scam_search()
    await run_rep(make_ctx, genuine_flat_case, make_company(), search=search, llm=verdicts())
    assert len(search.queries) == 4  # scam, reviews, redress, cmp (rogue checker fetched directly)
    assert all('"PRIME CITY LETTINGS LTD"' in q for q in search.queries)


async def test_snippet_about_a_same_name_company_elsewhere_is_dropped(
    make_ctx, genuine_flat_case
) -> None:
    llm = verdicts(
        verdict(0, "scam_report", SCAM_QUOTE),
        verdict(1, "different_company", "advertised a fake listing", about=False),
    )
    result = await run_rep(
        make_ctx, genuine_flat_case, make_company(), search=scam_search(), llm=llm
    )
    findings = by_prefix(result, "scam-report-")
    assert len(findings) == 1
    assert "example-reviews.org" not in findings[0].detail


async def test_llm_quote_not_found_in_the_snippet_is_dropped(make_ctx, genuine_flat_case) -> None:
    llm = verdicts(verdict(0, "scam_report", "they disappeared with my rent"))
    result = await run_rep(
        make_ctx, genuine_flat_case, make_company(), search=scam_search(), llm=llm
    )
    assert result.findings == [] and result.failed_checks == []


async def test_negative_review_is_medium_and_ids_use_the_url_hash(
    make_ctx, genuine_flat_case
) -> None:
    search = FakeSearch({"reviews Google": results("linkup_scam.json")[:1]})
    llm = verdicts(verdict(0, "negative_review", SCAM_QUOTE))
    result = await run_rep(make_ctx, genuine_flat_case, make_company(), search=search, llm=llm)
    [finding] = by_prefix(result, "negative-review-")
    assert finding.severity == "medium" and finding.confidence == 0.6
    assert finding.detail.startswith(f'A review of PRIME CITY LETTINGS LTD says: "{SCAM_QUOTE}".')
    assert (
        finding.id
        == f"companies_house:negative-review-{url_hash8(results('linkup_scam.json')[0].url)}"
    )


async def test_same_url_in_scam_and_reviews_is_deduped_before_filtering(
    make_ctx, genuine_flat_case
) -> None:
    same = results("linkup_scam.json")[:1]
    search = FakeSearch({"scam OR fraud": same, "reviews Google": same})
    llm = verdicts(verdict(0, "scam_report", SCAM_QUOTE), verdict(1, "scam_report", SCAM_QUOTE))
    result = await run_rep(make_ctx, genuine_flat_case, make_company(), search=search, llm=llm)
    user = llm.calls[0]["user"]
    assert user.count(same[0].url) == 1 and "[1]" not in user
    assert len(result.findings) == 1


def numbered_results(count: int) -> list[SearchResult]:
    return [
        SearchResult(
            title=f"Post {i}",
            url=f"https://example.org/post/{i}",
            snippet=f"Prime City Lettings Ltd kept my deposit in case {i}.",
        )
        for i in range(count)
    ]


async def test_at_most_three_findings_per_kind(make_ctx, genuine_flat_case) -> None:
    scam = numbered_results(5)
    reviews = [
        SearchResult(
            title=f"Review {i}",
            url=f"https://example.org/review/{i}",
            snippet=f"Prime City Lettings Ltd took money, review {i}.",
        )
        for i in range(4)
    ]
    search = FakeSearch({"scam OR fraud": scam, "reviews Google": reviews})
    items = [verdict(i, "scam_report", f"kept my deposit in case {i}") for i in range(5)]
    items += [verdict(5 + i, "negative_review", f"took money, review {i}") for i in range(4)]
    result = await run_rep(
        make_ctx, genuine_flat_case, make_company(), search=search, llm=verdicts(*items)
    )
    assert len(by_prefix(result, "scam-report-")) == 3
    assert len(by_prefix(result, "negative-review-")) == 3
    first = by_prefix(result, "scam-report-")
    assert {f.detail.split("Source: ")[1] for f in first} == {
        "https://example.org/post/0",
        "https://example.org/post/1",
        "https://example.org/post/2",
    }


async def test_llm_down_uses_keyword_fallback_with_lower_confidence(
    make_ctx, genuine_flat_case
) -> None:
    class RaisingLLM(FakeLLM):
        async def complete_json(self, system, user, schema, *, model=None):  # type: ignore[override]
            raise RuntimeError("model unavailable")

    search = FakeSearch({"scam OR fraud": results("linkup_scam.json")})
    result = await run_rep(
        make_ctx, genuine_flat_case, make_company(), search=search, llm=RaisingLLM()
    )
    findings = by_prefix(result, "scam-report-")
    assert findings and all(f.confidence == 0.6 for f in findings)
    assert all(
        quote_of(f) in results("linkup_scam.json")[0].snippet
        or quote_of(f) in results("linkup_scam.json")[1].snippet
        for f in findings
    )


async def test_one_failed_search_is_reported_not_treated_as_empty(
    make_ctx, genuine_flat_case
) -> None:
    class ScamDown(FakeSearch):
        async def search(self, query, *, depth="standard"):  # type: ignore[override]
            if "scam OR fraud" in query:
                raise httpx.ReadTimeout("slow")
            return await super().search(query, depth=depth)

    result = await run_rep(
        make_ctx, genuine_flat_case, make_company(), search=ScamDown(), llm=verdicts()
    )
    assert any(c.startswith("scam reports (Linkup: timeout") for c in result.failed_checks)
    assert len(result.failed_checks) == 1


# --- redress and CMP ------------------------------------------------------------------------


async def test_no_redress_or_cmp_hit_gives_no_finding_and_no_absence_claim(
    make_ctx, genuine_flat_case
) -> None:
    search = FakeSearch(
        {
            "Property Redress": [
                SearchResult(
                    title="Other",
                    url="https://example.org/x",
                    snippet="Some other agent, not ours.",
                )
            ]
        }
    )
    result = await run_rep(make_ctx, genuine_flat_case, larkfield(), search=search)
    assert result.findings == [] and result.failed_checks == []
    text = json.dumps([f.model_dump(mode="json") for f in result.findings] + result.failed_checks)
    assert ("not a" + " member") not in text.lower()


async def test_redress_page_that_does_not_name_the_company_clears_nothing(
    make_ctx, genuine_flat_case
) -> None:
    other = SearchResult(
        title="PRS",
        url="https://www.theprs.co.uk/about",
        snippet="The Property Redress Scheme is a redress scheme.",
    )
    result = await run_rep(
        make_ctx, genuine_flat_case, larkfield(), search=FakeSearch({"Property Redress": [other]})
    )
    assert result.findings == []


async def test_redress_hit_on_theprs_clears_with_the_url(make_ctx, genuine_flat_case) -> None:
    search = FakeSearch({"Property Redress": results("linkup_redress.json")})
    result = await run_rep(make_ctx, genuine_flat_case, larkfield(), search=search)
    [finding] = result.findings
    assert finding.id == "companies_house:redress-member"
    assert finding.supports == "cleared" and finding.severity == "low" and finding.confidence == 0.5
    assert "Property Redress Scheme" in finding.title
    assert "Source: https://www.theprs.co.uk/find-an-agent/larkfield-co-lettings" in finding.detail
    [ref] = finding.evidence
    assert ref.evidence_id == EV_WEB and "Larkfield & Co Lettings" in quote_of(ref)
    assert quote_of(ref) in results("linkup_redress.json")[0].snippet


async def test_redress_hit_by_company_number_only_clears(make_ctx, genuine_flat_case) -> None:
    hit = SearchResult(
        title="TPO",
        url="https://www.tpos.co.uk/members/09123456",
        snippet="Member firm, company number 09123456.",
    )
    result = await run_rep(
        make_ctx, genuine_flat_case, larkfield(), search=FakeSearch({"Property Redress": [hit]})
    )
    [finding] = result.findings
    assert "The Property Ombudsman" in finding.title and "09123456" in quote_of(finding)


async def test_redress_name_on_an_unrelated_domain_does_not_clear(
    make_ctx, genuine_flat_case
) -> None:
    result = await run_rep(
        make_ctx,
        genuine_flat_case,
        larkfield(),
        search=FakeSearch({"Property Redress": results("linkup_redress.json")[1:]}),
    )
    assert result.findings == []


async def test_cmp_hit_on_propertymark_clears(make_ctx, genuine_flat_case) -> None:
    search = FakeSearch({"client money": results("linkup_cmp.json")})
    result = await run_rep(make_ctx, genuine_flat_case, larkfield(), search=search)
    [finding] = result.findings
    assert finding.id == "companies_house:cmp-member" and finding.supports == "cleared"
    assert "Propertymark" in finding.detail
    assert (
        "Source: https://www.propertymark.co.uk/find-an-agent/larkfield-co-lettings.html"
        in finding.detail
    )


async def test_good_reviews_never_clear_anything(make_ctx, genuine_flat_case) -> None:
    praise = [
        SearchResult(
            title="Great",
            url="https://example.org/great",
            snippet="Larkfield & Co Lettings: five stars, lovely team.",
        )
    ]
    llm = verdicts(verdict(0, "irrelevant", "five stars", about=False))
    result = await run_rep(
        make_ctx,
        genuine_flat_case,
        larkfield(),
        search=FakeSearch({"reviews Google": praise}),
        llm=llm,
    )
    assert result.findings == []


# --- Rogue Checker --------------------------------------------------------------------------


async def test_rogue_number_match_is_high_with_exact_url_and_quote(
    make_ctx, genuine_flat_case
) -> None:
    router = rogue_ok(fixture_text("reputation", "rogue_hit.html"))
    search = FakeSearch()
    result = await run_rep(
        make_ctx, genuine_flat_case, make_company(), router=router, search=search
    )
    [finding] = result.findings
    assert finding.id == "companies_house:rogue-checker"
    assert finding.supports == "suspicious" and finding.severity == "high"
    assert finding.confidence == 0.9 and finding.hard_flag is False
    [ref] = finding.evidence
    assert ref.evidence_id == EV_ROGUE
    assert "Prime City Lettings Limited (10452757)" in quote_of(ref)
    assert "Banning order" in quote_of(ref) and "Monday 23 March 2026" in quote_of(ref)
    assert finding.detail.startswith(
        "The Mayor of London's checker records: Banning order by London Borough of Newham"
        " on 23 March 2026."
    )
    [request] = router.requests
    assert (
        request.url.params["name"] == "PRIME CITY LETTINGS LTD"
        and request.url.params["page"] == "0"
    )
    assert request.headers["user-agent"].startswith("Warden/")
    assert f"Source: {request.url}" in finding.detail
    assert not any("london.gov.uk" in q for q in search.queries)  # no Linkup fallback


async def test_rogue_miss_is_no_finding_and_no_fallback(make_ctx, genuine_flat_case) -> None:
    router = rogue_miss()
    search = FakeSearch()
    result = await run_rep(
        make_ctx, genuine_flat_case, make_company(), router=router, search=search
    )
    assert result.findings == [] and result.failed_checks == []
    assert len(router.requests) == 1
    assert not any("rogue" in q for q in search.queries)


async def test_expired_record_is_ignored(make_ctx, genuine_flat_case) -> None:
    router = rogue_ok(fixture_text("reputation", "rogue_hit.html"))
    # Primrose Hill's record expired on 3 June 2026, before TODAY (14 Nov 2026).
    expired = make_company("Primrose Hill Lettings Limited", "09876543", None)
    result = await run_rep(make_ctx, genuine_flat_case, expired, router=router)
    assert result.findings == []
    # Prime City Homes expired in 2020.
    older = make_company("Prime City Homes Ltd", "07654321", None)
    assert (await run_rep(make_ctx, genuine_flat_case, older, router=router)).findings == []


async def test_record_expiring_today_is_still_live(make_ctx, genuine_flat_case) -> None:
    html = page_html(
        [entry_html("Prime City Lettings Limited", "10452757", expires="Saturday 14 November 2026")]
    )
    result = await run_rep(make_ctx, genuine_flat_case, make_company(), router=rogue_ok(html))
    assert [f.id for f in result.findings] == ["companies_house:rogue-checker"]


async def test_name_match_on_an_entry_with_no_company_number_is_medium(
    make_ctx, genuine_flat_case
) -> None:
    html = page_html([entry_html("Prime City Lettings Limited", None)])
    [finding] = (
        await run_rep(make_ctx, genuine_flat_case, make_company(), router=rogue_ok(html))
    ).findings
    assert finding.id == "companies_house:rogue-checker-name"
    assert finding.severity == "medium" and finding.confidence == 0.6


async def test_same_name_but_a_different_company_number_is_dropped(
    make_ctx, genuine_flat_case
) -> None:
    router = rogue_ok(fixture_text("reputation", "rogue_hit.html"))
    # rogue_hit.html lists PRIME CITY LETTINGS (10452757); this company has another number.
    company = make_company("PRIME CITY LETTINGS LTD", "99999999")
    assert (await run_rep(make_ctx, genuine_flat_case, company, router=router)).findings == []


async def test_similar_but_different_name_does_not_match(make_ctx, genuine_flat_case) -> None:
    router = rogue_ok(fixture_text("reputation", "rogue_hit.html"))
    company = make_company("PRIME CITY LET LTD", "11111111")
    assert (await run_rep(make_ctx, genuine_flat_case, company, router=router)).findings == []


async def test_page_with_no_matching_entry_is_no_finding(make_ctx, genuine_flat_case) -> None:
    router = rogue_ok(page_html(filler(3)))
    search = FakeSearch()
    result = await run_rep(
        make_ctx, genuine_flat_case, make_company(), router=router, search=search
    )
    assert result.findings == [] and result.failed_checks == []
    assert len(router.requests) == 1 and not any("rogue" in q for q in search.queries)


@pytest.mark.parametrize(
    "router",
    [
        Router({("GET", ROGUE_PATH): (403, "Forbidden")}),
        Router({("GET", ROGUE_PATH): (200, fixture_text("reputation", "rogue_challenge.html"))}),
        Router(
            {
                ("GET", ROGUE_PATH): (
                    200,
                    "<html><body>Redesigned page with no entries</body></html>",
                )
            }
        ),
        Router(
            {("GET", ROGUE_PATH): lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow"))}
        ),
        Router({("GET", ROGUE_PATH): (500, "oops")}),
    ],
    ids=["403", "cloudflare-challenge", "unparseable", "timeout", "500"],
)
async def test_failed_direct_fetch_falls_back_to_linkup(
    make_ctx, genuine_flat_case, router
) -> None:
    search = FakeSearch({"site:london.gov.uk": results("linkup_rogue.json")})
    result = await run_rep(
        make_ctx, genuine_flat_case, make_company(), router=router, search=search
    )
    [finding] = result.findings
    assert finding.id == "companies_house:rogue-checker"
    [ref] = finding.evidence
    assert ref.evidence_id == EV_WEB and "(10452757)" in quote_of(ref)
    assert quote_of(ref) in results("linkup_rogue.json")[0].snippet
    assert "Source: https://www.london.gov.uk/" in finding.detail
    assert "Banning order by London Borough of Newham on 23 March 2026" in finding.detail
    assert len(router.requests) == 1  # a single try, then Linkup
    assert sum("site:london.gov.uk" in q for q in search.queries) == 1


async def test_linkup_fallback_ignores_expired_and_unrelated_results(
    make_ctx, genuine_flat_case
) -> None:
    expired = SearchResult(
        title="Checker",
        url="https://www.london.gov.uk/rogue-checker",
        snippet=(
            "Prime City Lettings Limited (10452757)\nEnforcement action type: Fine\n"
            "Record expires: Friday 1 March 2024"
        ),
    )
    elsewhere = SearchResult(
        title="Blog",
        url="https://blog.example.org/x",
        snippet="Prime City Lettings Limited (10452757) banned.",
    )
    result = await run_rep(
        make_ctx,
        genuine_flat_case,
        make_company(),
        router=Router({("GET", ROGUE_PATH): (403, "")}),
        search=FakeSearch({"site:london.gov.uk": [expired, elsewhere]}),
    )
    assert result.findings == [] and result.failed_checks == []


async def test_linkup_fallback_name_only_match_is_medium(make_ctx, genuine_flat_case) -> None:
    hit = SearchResult(
        title="Checker",
        url="https://www.london.gov.uk/rogue-checker",
        snippet="Prime City Lettings Ltd was fined. Enforcement action type: Civil penalty",
    )
    result = await run_rep(
        make_ctx,
        genuine_flat_case,
        make_company(),
        router=Router({("GET", ROGUE_PATH): (403, "")}),
        search=FakeSearch({"site:london.gov.uk": [hit]}),
    )
    [finding] = result.findings
    assert finding.id == "companies_house:rogue-checker-name" and finding.severity == "medium"
    assert quote_of(finding) in hit.snippet


async def test_direct_and_fallback_both_failing_is_a_failed_check(
    make_ctx, genuine_flat_case
) -> None:
    result = await run_rep(
        make_ctx,
        genuine_flat_case,
        make_company(),
        router=Router({("GET", ROGUE_PATH): (403, "")}),
        search=DownSearch(),
        llm=verdicts(),
    )
    rogue_failures = [
        c for c in result.failed_checks if c.startswith("London Rogue Landlord and Agent Checker (")
    ]
    assert len(rogue_failures) == 1 and "403" in rogue_failures[0]
    assert not by_prefix(result, "rogue")


async def test_linkup_down_gives_failed_checks_and_no_absence_claims(
    make_ctx, genuine_flat_case
) -> None:
    result = await run_rep(
        make_ctx, genuine_flat_case, make_company(), search=DownSearch(), llm=verdicts()
    )
    assert result.findings == [] and result.fatal is False
    checks = " | ".join(result.failed_checks)
    for expected in ("scam reports", "reviews", "redress scheme", "client money protection"):
        assert expected in checks
    assert all("Linkup" in c for c in result.failed_checks)


async def test_budget_exhausted_becomes_a_query_budget_failure(make_ctx, genuine_flat_case) -> None:
    result = await run_rep(
        make_ctx,
        genuine_flat_case,
        make_company(),
        budget=QueryBudget(limit=0),
        search=scam_search(),
        llm=verdicts(),
    )
    assert result.findings == []
    assert result.failed_checks and all("(query budget)" in c for c in result.failed_checks)
    assert not any("Linkup:" in c for c in result.failed_checks)


async def test_budget_exhausted_for_the_rogue_fallback_only(make_ctx, genuine_flat_case) -> None:
    result = await run_rep(
        make_ctx,
        genuine_flat_case,
        make_company(),
        router=Router({("GET", ROGUE_PATH): (403, "")}),
        budget=QueryBudget(limit=4),  # scam, reviews, redress, cmp use it all up
        llm=verdicts(),
    )
    assert result.failed_checks == ["London Rogue Landlord and Agent Checker (query budget)"]


async def test_second_page_fetched_when_first_page_is_full_with_no_match(
    make_ctx, genuine_flat_case
) -> None:
    pages = {
        "0": page_html(filler(10)),
        "1": page_html([entry_html("Prime City Lettings Limited", "10452757")] + filler(2, 10)),
    }
    router = Router(
        {("GET", ROGUE_PATH): lambda r: httpx.Response(200, text=pages[r.url.params["page"]])}
    )
    result = await run_rep(make_ctx, genuine_flat_case, make_company(), router=router)
    assert len(router.requests) == 2
    [finding] = result.findings
    assert finding.id == "companies_house:rogue-checker" and "page=1" in finding.detail


async def test_never_more_than_two_rogue_pages(make_ctx, genuine_flat_case) -> None:
    router = Router(
        {
            ("GET", ROGUE_PATH): lambda r: httpx.Response(
                200, text=page_html(filler(10, int(r.url.params["page"]) * 10))
            )
        }
    )
    result = await run_rep(make_ctx, genuine_flat_case, make_company(), router=router)
    assert len(router.requests) == 2 and result.findings == [] and result.failed_checks == []


async def test_second_page_not_fetched_when_page_zero_matches(make_ctx, genuine_flat_case) -> None:
    router = rogue_ok(
        page_html([entry_html("Prime City Lettings Limited", "10452757")] + filler(9))
    )
    result = await run_rep(make_ctx, genuine_flat_case, make_company(), router=router)
    assert len(router.requests) == 1 and len(result.findings) == 1


async def test_second_page_not_fetched_when_page_zero_is_short(make_ctx, genuine_flat_case) -> None:
    router = rogue_ok(page_html(filler(9)))
    await run_rep(make_ctx, genuine_flat_case, make_company(), router=router)
    assert len(router.requests) == 1


async def test_second_page_failure_falls_back_to_linkup(make_ctx, genuine_flat_case) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["page"] == "0":
            return httpx.Response(200, text=page_html(filler(10)))
        return httpx.Response(403)

    search = FakeSearch({"site:london.gov.uk": results("linkup_rogue.json")})
    result = await run_rep(
        make_ctx,
        genuine_flat_case,
        make_company(),
        router=Router({("GET", ROGUE_PATH): handler}),
        search=search,
    )
    assert [f.id for f in result.findings] == ["companies_house:rogue-checker"]
    assert result.findings[0].evidence[0].evidence_id == EV_WEB


# --- parsing --------------------------------------------------------------------------------


def test_parse_rogue_page_reads_every_entry_and_ignores_other_headings() -> None:
    records = parse_rogue_page(fixture_text("reputation", "rogue_hit.html"))
    assert [r.number for r in records] == ["09876543", "10452757", "07654321", "SC123456"]
    target = records[1]
    assert target.name == "Prime City Lettings Limited"
    assert target.action_type == "Banning order"
    assert target.authority == "London Borough of Newham"
    assert target.action_date == date(2026, 3, 23) and target.expires == date(2028, 3, 23)
    assert target.address == "12 Example Road, London E7 0AA"
    assert target.offence == "Unlicensed House in Multiple Occupation"
    assert target.quote == (
        "Prime City Lettings Limited (10452757) | Enforcement action type: Banning order"
        " | Enforcement date: Monday 23 March 2026"
    )
    # the footer's <h3> and <li> never attach to the last entry
    assert "contact" not in " ".join(records[-1].quote.lower().split())


def test_parse_rogue_page_without_number_in_heading() -> None:
    [record] = parse_rogue_page(
        "<h3 data-search-highlight>Sole Trader Agent</h3>"
        "<ul><li><strong>Offence:</strong>X</li></ul>"
    )
    assert record.name == "Sole Trader Agent" and record.number is None and record.offence == "X"


def test_parse_rogue_page_zero_pads_short_numbers() -> None:
    [record] = parse_rogue_page("<h3 data-search-highlight>Old Agent Ltd (123456)</h3>")
    assert record.number == "00123456"


def test_parse_rogue_page_with_no_entries_is_empty() -> None:
    assert parse_rogue_page(fixture_text("reputation", "rogue_miss.html")) == []
    assert parse_rogue_page("") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Monday 23 March 2026", date(2026, 3, 23)),
        ("23 March 2026", date(2026, 3, 23)),
        ("  Tuesday   3 June 2025 ", date(2025, 6, 3)),
        ("Sat 14 Nov 2026", date(2026, 11, 14)),
        ("1st December 2026", date(2026, 12, 1)),
        ("2026-03-23", date(2026, 3, 23)),
        ("23/03/2026", date(2026, 3, 23)),
        ("Sept 9 2026", None),
        ("", None),
        (None, None),
        ("sometime soon", None),
        ("31 February 2026", None),
    ],
)
def test_parse_rogue_date(text: str | None, expected: date | None) -> None:
    assert parse_rogue_date(text) == expected


def test_rogue_match_number_wins_a_different_number_never_matches_and_name_needs_no_number() -> (
    None
):
    company = make_company()
    rec = parse_rogue_page(entry_html("Totally Different Name", "10452757"))[0]
    assert rogue_match(rec, company) == "number"
    rec = parse_rogue_page(entry_html("Prime City Lettings Limited", "55555555"))[0]
    assert rogue_match(rec, company) is None  # same name, different number: a different company
    rec = parse_rogue_page(entry_html("Prime City Lettings Limited", None))[0]
    assert rec.number is None and rogue_match(rec, company) == "name"
    rec = parse_rogue_page(entry_html("Prime City Homes Limited", None))[0]
    assert rogue_match(rec, company) is None


# --- invariants -----------------------------------------------------------------------------


async def test_every_finding_is_quoted_sourced_and_never_a_hard_flag(
    make_ctx, genuine_flat_case
) -> None:
    search = FakeSearch(
        {
            "scam OR fraud": results("linkup_scam.json"),
            "Property Redress": results("linkup_redress.json"),
            "client money": results("linkup_cmp.json"),
        }
    )
    llm = verdicts(verdict(0, "scam_report", SCAM_QUOTE))
    router = rogue_ok(fixture_text("reputation", "rogue_hit.html"))
    company = make_company("LARKFIELD & CO LETTINGS LTD", "10452757")
    result = await run_rep(
        make_ctx, genuine_flat_case, company, router=router, search=search, llm=llm
    )
    assert {f.id.split(":")[1].split("-")[0] for f in result.findings} >= {
        "scam",
        "redress",
        "cmp",
        "rogue",
    }
    for f in result.findings:
        assert f.id.startswith("companies_house:")
        assert f.evidence and all((e.quote or "").strip() for e in f.evidence)
        assert all(len(e.quote or "") <= 200 for e in f.evidence)
        assert any(e.evidence_id in EXTERNAL_EVIDENCE_IDS for e in f.evidence)
        assert "Source: http" in f.detail
        assert f.hard_flag is False
        assert f.agent == "companies_house" and f.check_id == "landlord_identity"
    assert result.facts == [] and result.questions == [] and result.fatal is False


async def test_module_never_raises_when_a_helper_blows_up(
    make_ctx, genuine_flat_case, monkeypatch
) -> None:
    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(reputation, "filter_snippets", boom)
    result = await run_rep(make_ctx, genuine_flat_case, make_company(), search=scam_search())
    assert result.failed_checks == ["reputation checks (unexpected error)"]


async def test_company_without_a_name_does_nothing(make_ctx, genuine_flat_case) -> None:
    router, search = rogue_miss(), FakeSearch()
    blank = make_company("", "10452757", None)
    result = await run_rep(make_ctx, genuine_flat_case, blank, router=router, search=search)
    assert result.findings == [] and router.requests == [] and search.queries == []


def test_the_absence_phrase_appears_nowhere_in_the_modules_code_or_prompts() -> None:
    phrase = "not a" + " member"
    for path in AGENT_DIR.rglob("*"):
        if path.is_file() and "tests" not in path.parts and path.suffix in {".py", ".md"}:
            assert phrase not in path.read_text().lower(), path
