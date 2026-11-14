"""Agent tests: the shell (Phase 1) and every Appendix F scenario run through the whole agent."""

from app.agents.companies_house.agent import CompaniesHouseAgent
from app.agents.companies_house.testing import Router, no_sleep
from app.contracts import AgentStatus, Case
from app.core.agent import hash_slice


async def test_skipped_without_company_and_no_http(overseas_landlord_case: Case, make_ctx) -> None:
    router = Router()
    report = await CompaniesHouseAgent(sleep=no_sleep).run(
        overseas_landlord_case, await make_ctx(router)
    )
    assert report.status == AgentStatus.SKIPPED
    assert report.error == "no company name or number"
    assert router.requests == []


async def test_missing_ch_key_is_error_with_zero_calls(
    fake_agency_case: Case, make_ctx, ch_settings
) -> None:
    router = Router()
    ctx = await make_ctx(
        router, settings=ch_settings.model_copy(update={"companies_house_api_key": ""})
    )
    report = await CompaniesHouseAgent(sleep=no_sleep).run(fake_agency_case, ctx)
    assert report.status == AgentStatus.ERROR
    assert report.error == "COMPANIES_HOUSE_API_KEY is not set"
    assert router.requests == []


async def test_company_the_register_does_not_know_still_gives_an_ok_report(
    genuine_flat_case: Case, make_ctx
) -> None:
    # An empty Router 404s everything: the number is "not found", which is a finding, not an error.
    report = await CompaniesHouseAgent(sleep=no_sleep).run(genuine_flat_case, await make_ctx())
    assert report.status == AgentStatus.OK
    assert report.agent == "companies_house"
    assert [f.id for f in report.findings if f.hard_flag] == ["companies_house:not-found"]


def test_timeout_is_120() -> None:
    assert CompaniesHouseAgent.timeout_s == 120.0


def test_input_slice_adds_postcode_and_contacts(genuine_flat_case: Case) -> None:
    agent = CompaniesHouseAgent()
    data = agent.input_slice(genuine_flat_case)
    assert data["listing_postcode"] == "SE1 7LP"
    assert data["contacts"] == []  # agent chat names no email/phone in this fixture
    assert "landlord" in data and "messages" not in data


def test_new_contact_changes_the_hash_but_unrelated_messages_do_not(
    genuine_flat_case: Case,
) -> None:
    agent = CompaniesHouseAgent()
    base = hash_slice(agent.input_slice(genuine_flat_case))

    unrelated = genuine_flat_case.model_copy(deep=True)
    unrelated.messages[0].text += " Thanks again!"
    assert hash_slice(agent.input_slice(unrelated)) == base

    with_email = genuine_flat_case.model_copy(deep=True)
    assert with_email.landlord is not None
    with_email.landlord.email = "new@agency.co.uk"
    assert hash_slice(agent.input_slice(with_email)) != base


# ===== Phase 3: every Appendix F scenario, run through the whole agent ========================

import json  # noqa: E402
from typing import Any  # noqa: E402

from app.agents.companies_house.constants import (  # noqa: E402
    EXTERNAL_EVIDENCE_IDS,
    ROGUE_CHECKER_URL,
)
from app.agents.companies_house.modules import property as property_module  # noqa: E402
from app.agents.companies_house.stub import CompaniesHouseStub  # noqa: E402
from app.agents.companies_house.testing import (  # noqa: E402
    TODAY,
    fixture_json,
    fixture_text,
)
from app.contracts import AgentReport  # noqa: E402
from app.core.search import FakeSearch, SearchResult  # noqa: E402

NOT_RUN = "companies_house:not-run-"
HARD_FLAGS = {"companies_house:not-found", "companies_house:dissolved"}


def assert_invariants(report: AgentReport) -> None:
    """Appendix F invariant: quotes, sources, hard flags, facts. Run on every report we make."""
    for f in report.findings:
        assert f.id.startswith("companies_house:")
        assert f.evidence and all(e.quote for e in f.evidence)
        if f.id.startswith(NOT_RUN):
            # NOTE: not-run notes cite evidence id "companies_house" (App. D) but have no URL to
            # cite, so the Source rule applies to every other external finding.
            assert f.severity == "info" and f.confidence == 0.0
        elif any(e.evidence_id in EXTERNAL_EVIDENCE_IDS for e in f.evidence):
            assert "Source: http" in f.detail
        if f.hard_flag:
            assert f.id in HARD_FLAGS
    assert not any(f.key.value in {"address", "landlord_name"} for f in report.facts)


def genuine_routes(extra: dict[tuple[str, str], Any] | None = None) -> dict:
    routes: dict[tuple[str, str], Any] = {
        ("GET", "/company/09123456"): (200, fixture_json("register", "company_active_old.json")),
        ("GET", "/company/09123456/officers"): (
            200,
            fixture_json("register", "officers_larkfield.json"),
        ),
        ("GET", "/search/disqualified-officers"): (200, {"items": []}),
        ("GET", ROGUE_CHECKER_URL): (200, fixture_text("reputation", "rogue_miss.html")),
        ("GET", "/postcodes/"): (200, {"result": {"admin_district": "Southwark"}}),
    }
    routes.update(extra or {})
    return routes


def redress_search() -> FakeSearch:
    return FakeSearch(
        {
            "Property Redress Scheme": [
                SearchResult(
                    title="Find a member | The Property Redress Scheme",
                    url="https://www.theprs.co.uk/find-a-member/larkfield",
                    snippet="Larkfield & Co Lettings Ltd is a registered member of the scheme.",
                )
            ]
        }
    )


def with_landlord(case: Case, **fields: Any) -> Case:
    out = case.model_copy(deep=True)
    assert out.landlord is not None
    for key, value in fields.items():
        setattr(out.landlord, key, value)
    return out


async def run_agent(case: Case, make_ctx, routes: Router | dict, **ctx_kwargs: Any) -> AgentReport:
    router = routes if isinstance(routes, Router) else Router(routes)
    ctx = await make_ctx(router, **ctx_kwargs)
    report = await CompaniesHouseAgent(today=TODAY, sleep=no_sleep).run(case, ctx)
    assert_invariants(report)
    return report


def by_id(report: AgentReport) -> dict[str, Any]:
    return {f.id: f for f in report.findings}


async def test_fake_agency_dissolved_company_is_a_hard_flag_on_landlord_identity(
    fake_agency_case: Case, make_ctx
) -> None:
    routes = {
        ("GET", "/search/companies"): (200, fixture_json("register", "search_prime_city.json")),
        ("GET", "/company/11223344"): (200, fixture_json("register", "company_dissolved.json")),
    }
    report = await run_agent(fake_agency_case, make_ctx, routes)
    flag = by_id(report)["companies_house:dissolved"]
    assert report.status == AgentStatus.OK
    assert flag.hard_flag and flag.severity == "critical" and flag.check_id == "landlord_identity"
    assert [f.id for f in report.findings if f.hard_flag] == ["companies_house:dissolved"]
    assert report.findings[0].id == "companies_house:dissolved"  # hard flags sort first


async def test_fake_agency_no_match_is_high_not_hard_and_asks_for_the_number(
    fake_agency_case: Case, make_ctx
) -> None:
    routes = {("GET", "/search/companies"): (200, {"items": []})}
    report = await run_agent(fake_agency_case, make_ctx, routes)
    finding = by_id(report)["companies_house:name-no-match"]
    assert report.status == AgentStatus.OK
    assert finding.severity == "high" and not finding.hard_flag
    assert any("company number" in q for q in report.questions)
    assert report.facts == []


async def test_genuine_flat_is_cleared_with_no_suspicious_findings(
    genuine_flat_case: Case, make_ctx
) -> None:
    report = await run_agent(genuine_flat_case, make_ctx, genuine_routes(), search=redress_search())
    assert report.status == AgentStatus.OK
    ids = set(by_id(report))
    assert {"companies_house:registered-active", "companies_house:redress-member"} <= ids
    assert [f for f in report.findings if f.supports == "suspicious"] == []
    assert [(f.key.value, f.value) for f in report.facts] == [("company_number", "09123456")]


async def test_number_that_returns_404_is_a_hard_flag(genuine_flat_case: Case, make_ctx) -> None:
    case = with_landlord(genuine_flat_case, company_number="99999999")
    report = await run_agent(case, make_ctx, {})  # every route 404s
    flag = by_id(report)["companies_house:not-found"]
    assert flag.hard_flag and flag.severity == "critical"
    assert report.facts == []


async def test_young_company_at_a_virtual_office_flags_both_and_clears_nothing(
    genuine_flat_case: Case, make_ctx
) -> None:
    case = with_landlord(genuine_flat_case, company_number="15551234")
    routes = genuine_routes(
        {
            ("GET", "/company/15551234"): (200, fixture_json("register", "company_young.json")),
            ("GET", "/company/15551234/officers"): (200, {"items": []}),
        }
    )
    report = await run_agent(case, make_ctx, routes)
    ids = set(by_id(report))
    assert {"companies_house:young-company", "companies_house:virtual-office"} <= ids
    assert by_id(report)["companies_house:young-company"].severity == "medium"
    assert by_id(report)["companies_house:virtual-office"].severity == "low"
    assert [f for f in report.findings if f.supports == "cleared"] == []


async def test_companies_house_500_three_times_is_an_error_with_no_findings(
    genuine_flat_case: Case, make_ctx
) -> None:
    router = Router({("GET", "/company/09123456"): (500, "")})
    report = await run_agent(genuine_flat_case, make_ctx, router)
    assert report.status == AgentStatus.ERROR
    assert report.error is not None and "3 attempts" in report.error
    assert report.findings == [] and report.facts == []
    assert len(router.calls("/company/09123456")) == 3


async def test_linkup_down_keeps_register_findings_and_adds_a_not_run_note(
    genuine_flat_case: Case, make_ctx
) -> None:
    class Down(FakeSearch):
        async def search(self, query, *, depth="standard"):  # type: ignore[override]
            raise RuntimeError("linkup down")

    report = await run_agent(genuine_flat_case, make_ctx, genuine_routes(), search=Down())
    found = by_id(report)
    assert report.status == AgentStatus.OK
    assert "companies_house:registered-active" in found  # register still reported
    note = found["companies_house:not-run-reputation"]
    assert note.severity == "info" and note.confidence == 0.0
    assert "scam reports" in note.detail and "Linkup" in note.detail
    assert "companies_house:redress-member" not in found  # a failure is not a clear either


async def test_negotiator_who_is_not_an_officer_never_flips_the_check(
    genuine_flat_case: Case, make_ctx
) -> None:
    case = with_landlord(genuine_flat_case, name="Sam Patel")
    report = await run_agent(case, make_ctx, genuine_routes(), search=redress_search())
    mismatch = by_id(report)["companies_house:officer-mismatch"]
    assert mismatch.confidence == 0.5 and mismatch.severity == "medium"
    # The check tracker flips on suspicious findings with severity >= medium AND confidence >= 0.6.
    flippers = [
        f
        for f in report.findings
        if f.supports == "suspicious"
        and f.severity in {"critical", "high", "medium"}
        and f.confidence >= 0.6
    ]
    assert flippers == []


async def test_overseas_landlord_is_skipped_with_zero_http_calls(
    overseas_landlord_case: Case, make_ctx
) -> None:
    router = Router()
    report = await run_agent(overseas_landlord_case, make_ctx, router)
    assert report.status == AgentStatus.SKIPPED
    assert router.requests == []


async def test_stub_report_is_valid_and_matches_the_fixture(
    fake_agency_case: Case, fixtures_dir, make_ctx
) -> None:
    fixture = json.loads((fixtures_dir / "reports" / "companies_house.json").read_text())
    report = await CompaniesHouseStub().run(fake_agency_case, await make_ctx())
    assert AgentReport.model_validate(report.model_dump()) == report
    assert [f.id for f in report.findings] == [f["id"] for f in fixture["findings"]]
    assert [f.hard_flag for f in report.findings] == [f["hard_flag"] for f in fixture["findings"]]


async def test_webmail_contact_adds_a_low_finding_and_an_email_domain_fact(
    genuine_flat_case: Case, make_ctx
) -> None:
    case = with_landlord(genuine_flat_case, email="lettings.larkfield@gmail.com")
    report = await run_agent(case, make_ctx, genuine_routes(), search=redress_search())
    webmail = by_id(report)["companies_house:webmail"]
    assert webmail.severity == "low" and webmail.confidence == 0.5
    facts = {(f.key.value, f.value) for f in report.facts}
    assert facts == {("company_number", "09123456"), ("email_domain", "gmail.com")}


async def test_invalid_listing_postcode_is_reported_by_the_property_module(
    genuine_flat_case: Case, make_ctx
) -> None:
    routes = genuine_routes({("GET", "/postcodes/"): (404, {"status": 404})})
    report = await run_agent(genuine_flat_case, make_ctx, routes, search=redress_search())
    assert by_id(report)["companies_house:postcode-invalid"].severity == "medium"


async def test_a_crashing_module_becomes_a_not_run_note_and_does_not_sink_the_report(
    genuine_flat_case: Case, make_ctx, monkeypatch
) -> None:
    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("module bug")

    monkeypatch.setattr(property_module, "run", boom)
    report = await run_agent(genuine_flat_case, make_ctx, genuine_routes(), search=redress_search())
    assert report.status == AgentStatus.OK
    assert "companies_house:registered-active" in by_id(report)
    assert "companies_house:not-run-property" in by_id(report)


async def test_finding_ids_are_stable_across_reruns(genuine_flat_case: Case, make_ctx) -> None:
    first = await run_agent(genuine_flat_case, make_ctx, genuine_routes(), search=redress_search())
    second = await run_agent(genuine_flat_case, make_ctx, genuine_routes(), search=redress_search())
    assert [f.id for f in first.findings] == [f.id for f in second.findings]
    assert len({f.id for f in first.findings}) == len(first.findings)
    assert first.input_hash == second.input_hash


async def test_a_module_that_overruns_the_deadline_becomes_a_note_and_register_survives(
    genuine_flat_case: Case, make_ctx, monkeypatch
) -> None:
    import asyncio

    async def never_finishes(*args: Any, **kwargs: Any) -> Any:
        await asyncio.Event().wait()

    monkeypatch.setattr(property_module, "run", never_finishes)
    router = Router(genuine_routes())
    ctx = await make_ctx(router, search=redress_search())
    agent = CompaniesHouseAgent(today=TODAY, sleep=no_sleep, deadline_s=0.05)
    report = await agent.run(genuine_flat_case, ctx)
    assert_invariants(report)
    assert report.status == AgentStatus.OK
    found = by_id(report)
    assert "companies_house:registered-active" in found
    assert "timed out" in found["companies_house:not-run-property"].detail
