"""Register module tests: pure rules first (one per plan 5.3 row), then offline I/O scenarios."""

import base64
from copy import deepcopy
from typing import Any

import pytest

from app.agents.companies_house.constants import CONF, DEAD_STATUSES
from app.agents.companies_house.models import (
    CompanyProfile,
    DisqualifiedHit,
    Officer,
    OfficerList,
    RegisterResult,
    SearchHit,
)
from app.agents.companies_house.modules import register
from app.agents.companies_house.modules.register import (
    Subject,
    dob_agrees,
    evaluate,
    find_disqualified,
    finding_ambiguous,
    finding_name_no_match,
    officer_search_name,
    rank_hits,
    rule_dissolved,
    rule_dormant,
    rule_insolvency_history,
    rule_name_number_mismatch,
    rule_non_property_sic,
    rule_not_found,
    rule_officer_mismatch,
    rule_overdue_filings,
    rule_registered_active,
    rule_strike_off,
    rule_virtual_office,
    rule_young_company,
)
from app.agents.companies_house.testing import TODAY, Router, fixture_json, no_sleep
from app.contracts import Case, CheckId, EvidenceRef, Fact, FactKey, Finding, Severity

# --- helpers ---------------------------------------------------------------------------------


def load(name: str) -> Any:
    return fixture_json("register", name)


def profile_dict(**overrides: Any) -> dict[str, Any]:
    data = load("company_active_old.json")
    data.update(overrides)
    return data


def prof(**overrides: Any) -> CompanyProfile:
    return CompanyProfile.model_validate(profile_dict(**overrides))


def subj(profile: CompanyProfile | None = None, **kwargs: Any) -> Subject:
    return Subject(
        profile=profile or prof(),
        number=kwargs.pop("number", "09123456"),
        matched_by=kwargs.pop("matched_by", "number"),
        **kwargs,
    )


def officers(*people: dict[str, Any], active_count: int | None = None) -> OfficerList:
    return OfficerList.model_validate({"items": list(people), "active_count": active_count})


def director(name: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "officer_role": "director", **extra}


def ids(findings: list[Finding]) -> list[str]:
    return [f.id for f in findings]


def by_id(findings: list[Finding], slug: str) -> Finding:
    matches = [f for f in findings if f.id == f"companies_house:{slug}"]
    assert matches, f"no {slug} finding in {ids(findings)}"
    return matches[0]


def hit(title: str, number: str, status: str = "active") -> SearchHit:
    return SearchHit(title=title, company_number=number, company_status=status)


# --- pure rules: one test per row of the plan 5.3 table --------------------------------------


def test_not_found_is_a_critical_hard_flag_on_landlord_identity() -> None:
    f = rule_not_found("00000001", [])
    assert f.id == "companies_house:not-found"
    assert (f.severity, f.hard_flag, f.supports) == (Severity.CRITICAL, True, "suspicious")
    assert f.check_id == CheckId.LANDLORD_IDENTITY
    assert f.confidence == CONF["not-found"]
    assert [e.quote for e in f.evidence] == [
        "company_number: 00000001",
        "http_status: 404 not found",
    ]
    assert "doesn't exist in the official UK register" in f.detail


def test_dissolved_status_is_a_critical_hard_flag_with_the_office_in_the_detail() -> None:
    s = subj(CompanyProfile.model_validate(load("company_dissolved.json")), number="11223344")
    f = rule_dissolved(s)
    assert f is not None
    assert f.id == "companies_house:dissolved"
    assert (f.severity, f.hard_flag) == (Severity.CRITICAL, True)
    assert f.check_id == CheckId.LANDLORD_IDENTITY
    assert f.title == "PRIME CITY LETTINGS LTD is dissolved on Companies House"
    assert f.evidence[0].quote == "company_status: dissolved"
    assert "71-75 Shelton Street" in f.detail


@pytest.mark.parametrize("status", sorted(DEAD_STATUSES))
def test_every_dead_status_fires_the_dissolved_hard_flag(status: str) -> None:
    f = rule_dissolved(subj(prof(company_status=status)))
    assert f is not None and f.hard_flag and f.severity == Severity.CRITICAL


@pytest.mark.parametrize("status", ["active", "voluntary-arrangement", "open", "dormant"])
def test_live_statuses_including_voluntary_arrangement_are_not_dead(status: str) -> None:
    assert rule_dissolved(subj(prof(company_status=status))) is None


def test_name_no_match_is_high_suspicious_and_not_a_hard_flag() -> None:
    hits = [SearchHit.model_validate(i) for i in load("search_no_match.json")["items"]]
    decision = rank_hits("Prime City Lettings Ltd", hits)
    f = finding_name_no_match("Prime City Lettings Ltd", decision, [])
    assert decision.kind == "none"
    assert f.id == "companies_house:name-no-match"
    assert (f.severity, f.hard_flag, f.supports) == (Severity.HIGH, False, "suspicious")
    assert f.confidence == CONF["name-no-match"]
    assert f.evidence[0].quote == "search_query: Prime City Lettings Ltd"
    assert (f.evidence[1].quote or "").startswith("search_results: 0 hits >= 90")
    assert "search/companies?q=Prime+City+Lettings+Ltd" in f.detail


def test_name_no_match_with_an_empty_search_still_quotes_the_result() -> None:
    f = finding_name_no_match("Ghost Ltd", rank_hits("Ghost Ltd", []), [])
    assert f.evidence[1].quote == "search_results: 0 hits >= 90 (no results)"


def test_ambiguous_match_lists_up_to_three_candidates_and_is_medium_not_hard() -> None:
    hits = [SearchHit.model_validate(i) for i in load("search_ambiguous.json")["items"]]
    decision = rank_hits("Oakwood Lettings Ltd", hits)
    f = finding_ambiguous("Oakwood Lettings Ltd", decision, [])
    assert decision.kind == "ambiguous" and len(decision.candidates) == 2
    assert f.id == "companies_house:ambiguous-match"
    assert (f.severity, f.hard_flag, f.supports) == (Severity.MEDIUM, False, "suspicious")
    assert f.confidence == CONF["ambiguous-match"]
    assert "OAKWOOD LETTINGS LTD (10000001, active)" in f.detail
    assert "OAKWOOD LETTINGS LIMITED (12000002, dissolved)" in f.detail
    assert "OAKWOOD LETTING SERVICES" not in f.detail


def test_young_company_under_twelve_months_is_medium() -> None:
    f = rule_young_company(subj(prof(date_of_creation="2026-06-01")), TODAY)
    assert f is not None
    assert (f.id, f.severity, f.supports) == (
        "companies_house:young-company",
        Severity.MEDIUM,
        "suspicious",
    )
    assert f.title.endswith("was set up 5 months ago")
    assert f.confidence == CONF["young-company"]
    assert f.evidence[0].quote == "date_of_creation: 2026-06-01"


def test_company_exactly_twelve_months_old_is_not_young() -> None:
    assert rule_young_company(subj(prof(date_of_creation="2025-11-14")), TODAY) is None
    assert rule_young_company(subj(prof(date_of_creation="2025-11-15")), TODAY) is not None


def test_officer_mismatch_is_medium_with_confidence_that_cannot_flip_the_check() -> None:
    s = subj()
    f = rule_officer_mismatch(s, officers(director("CLARKE, Hannah Louise")), "Sam Patel")
    assert f is not None
    assert (f.id, f.severity, f.confidence) == (
        "companies_house:officer-mismatch",
        Severity.MEDIUM,
        0.5,
    )
    assert f.title == "Sam Patel isn't listed as a director of LARKFIELD & CO LETTINGS LTD"
    assert "common for staff, so ask the agent who the director is" in f.detail
    assert f.evidence[0].quote == "officers: CLARKE, Hannah Louise"


def test_disqualified_director_is_high_and_names_the_officer() -> None:
    officer = Officer.model_validate(director("CLARKE, Hannah Louise"))
    dq = DisqualifiedHit(title="Hannah Louise CLARKE", description="Banned for 7 years.")
    f = register.rule_disqualified(subj(), [(officer, dq)])
    assert f is not None
    assert (f.id, f.severity, f.confidence) == (
        "companies_house:disqualified-director",
        Severity.HIGH,
        CONF["disqualified-director"],
    )
    assert f.title == "A director of LARKFIELD & CO LETTINGS LTD is disqualified"
    assert "CLARKE, Hannah Louise is disqualified from being a company director" in f.detail
    assert f.evidence[0].quote == "disqualified_officer: Hannah Louise CLARKE"


def test_overdue_filings_fires_for_accounts_and_for_confirmation_statement_separately() -> None:
    accounts = rule_overdue_filings(subj(prof(accounts={"overdue": True})))
    statement = rule_overdue_filings(subj(prof(confirmation_statement={"overdue": True})))
    assert accounts is not None and statement is not None
    assert accounts.evidence[0].quote == "accounts.overdue: true"
    assert statement.evidence[0].quote == "confirmation_statement.overdue: true"
    assert (accounts.id, accounts.severity) == ("companies_house:overdue-filings", Severity.LOW)
    assert accounts.confidence == CONF["overdue-filings"]
    assert rule_overdue_filings(subj()) is None


def test_overdue_filings_ignores_missing_accounts_for_a_new_company() -> None:
    assert rule_overdue_filings(subj(prof(accounts=None, confirmation_statement=None))) is None


def test_dormant_accounts_are_medium() -> None:
    p = prof(accounts={"overdue": False, "last_accounts": {"type": "dormant"}})
    f = rule_dormant(subj(p))
    assert f is not None
    assert (f.id, f.severity) == ("companies_house:dormant", Severity.MEDIUM)
    assert f.evidence[0].quote == "accounts.last_accounts.type: dormant"
    assert rule_dormant(subj()) is None


def test_insolvency_history_is_medium_and_skipped_for_a_dead_company() -> None:
    f = rule_insolvency_history(subj(prof(has_insolvency_history=True)))
    assert f is not None
    assert (f.id, f.severity) == ("companies_house:insolvency-history", Severity.MEDIUM)
    dead = prof(has_insolvency_history=True, company_status="liquidation")
    assert rule_insolvency_history(subj(dead)) is None


def test_non_property_sic_is_low_and_lists_the_codes() -> None:
    f = rule_non_property_sic(subj(prof(sic_codes=["47190", "62012"])))
    assert f is not None
    assert (f.id, f.severity) == ("companies_house:non-property-sic", Severity.LOW)
    assert f.evidence[0].quote == "sic_codes: 47190, 62012"
    assert "(47190, 62012)" in f.detail


def test_non_property_sic_does_not_fire_without_codes_or_with_one_property_code() -> None:
    assert rule_non_property_sic(subj(prof(sic_codes=[]))) is None
    assert rule_non_property_sic(subj(prof(sic_codes=["47190", "68320"]))) is None
    without_key = {k: v for k, v in profile_dict().items() if k != "sic_codes"}
    assert rule_non_property_sic(subj(CompanyProfile.model_validate(without_key))) is None


def test_virtual_office_matches_markers_case_insensitively_and_hedges_in_the_detail() -> None:
    p = prof(
        registered_office_address={"address_line_1": "71-75 SHELTON STREET", "locality": "London"}
    )
    f = rule_virtual_office(subj(p))
    assert f is not None
    assert (f.id, f.severity) == ("companies_house:virtual-office", Severity.LOW)
    assert "a common virtual office / formation agent address, used by many legitimate" in f.detail
    assert rule_virtual_office(subj()) is None


def test_registered_active_clears_an_old_active_company_with_clean_filings() -> None:
    f = rule_registered_active(subj(), TODAY)
    assert f is not None
    assert (f.id, f.supports, f.severity) == (
        "companies_house:registered-active",
        "cleared",
        Severity.LOW,
    )
    assert f.confidence == CONF["registered-active"] == 0.6
    assert f.hard_flag is False and f.check_id == CheckId.LANDLORD_IDENTITY
    assert f.title == "LARKFIELD & CO LETTINGS LTD is active on Companies House"
    assert "Registered on 3 July 2014 (12 years ago)" in f.detail
    assert "Registered office: 21 Mercer Street, London, SE1 7LP" in f.detail


@pytest.mark.parametrize(
    "overrides",
    [
        {"company_status": "voluntary-arrangement"},
        {"date_of_creation": "2025-03-01"},  # 20 months: between young and established
        {"date_of_creation": None},
        {"accounts": {"overdue": True}},
        {"confirmation_statement": {"overdue": True}},
        {"accounts": {"overdue": False, "last_accounts": {"type": "dormant"}}},
        {"company_status_detail": "active-proposal-to-strike-off"},
    ],
    ids=[
        "not-active",
        "12-24-months-old",
        "unknown-age",
        "accounts-overdue",
        "statement-overdue",
        "dormant",
        "strike-off",
    ],
)
def test_registered_active_does_not_clear_when_any_condition_fails(
    overrides: dict[str, Any],
) -> None:
    assert rule_registered_active(subj(prof(**overrides)), TODAY) is None


def test_registered_active_does_not_clear_when_the_number_belongs_to_another_name() -> None:
    s = subj(supplied_name="Prime City Lettings Ltd")
    assert rule_registered_active(s, TODAY) is None


def test_registered_active_clears_when_the_number_and_supplied_name_agree() -> None:
    s = subj(supplied_name="Larkfield & Co Lettings Ltd")
    assert rule_registered_active(s, TODAY) is not None


# --- pure rules: edge cases (plan appendix I) ------------------------------------------------


def test_twelve_to_twenty_four_month_old_company_gets_no_age_finding_and_no_clear() -> None:
    s = subj(prof(date_of_creation="2025-03-01"))
    assert evaluate(s, today=TODAY) == []


def test_company_with_only_a_name_and_status_produces_no_findings_not_errors() -> None:
    bare = CompanyProfile.model_validate({"company_name": "BARE LTD", "company_status": "active"})
    assert evaluate(subj(bare), today=TODAY) == []


def test_name_number_mismatch_is_high_and_quotes_both_names_in_the_detail() -> None:
    s = subj(supplied_name="Prime City Lettings Ltd")
    f = rule_name_number_mismatch(s)
    assert f is not None
    assert (f.id, f.severity, f.hard_flag) == (
        "companies_house:name-number-mismatch",
        Severity.HIGH,
        False,
    )
    assert f.confidence == CONF["name-number-mismatch"] == 0.9
    assert (
        "The company number belongs to LARKFIELD & CO LETTINGS LTD, not Prime City Lettings Ltd."
        in f.detail
    )


def test_name_number_mismatch_stays_quiet_for_the_same_name_or_a_name_resolved_company() -> None:
    assert (
        rule_name_number_mismatch(subj(supplied_name="Larkfield and Co Lettings Limited")) is None
    )
    assert rule_name_number_mismatch(subj()) is None
    assert rule_name_number_mismatch(subj(matched_by="name", supplied_name="Other Ltd")) is None


def test_evaluate_with_a_mismatch_emits_the_mismatch_and_never_registered_active() -> None:
    found = evaluate(subj(supplied_name="Prime City Lettings Ltd"), today=TODAY)
    assert "companies_house:name-number-mismatch" in ids(found)
    assert "companies_house:registered-active" not in ids(found)


@pytest.mark.parametrize(
    "detail", ["active-proposal-to-strike-off", "petition-to-restore-dissolved"]
)
def test_strike_off_details_are_medium_suspicious_and_never_clear(detail: str) -> None:
    s = subj(prof(company_status_detail=detail))
    f = rule_strike_off(s)
    assert f is not None
    assert (f.id, f.severity, f.supports, f.hard_flag) == (
        "companies_house:strike-off-proposed",
        Severity.MEDIUM,
        "suspicious",
        False,
    )
    assert f.confidence == CONF["strike-off-proposed"] == 0.7
    assert f.evidence[0].quote == f"company_status_detail: {detail}"
    assert "companies_house:registered-active" not in ids(evaluate(s, today=TODAY))


def test_dead_status_with_strike_off_detail_only_fires_the_dissolved_hard_flag() -> None:
    s = subj(
        prof(company_status="dissolved", company_status_detail="petition-to-restore-dissolved")
    )
    assert rule_strike_off(s) is None
    assert ids(evaluate(s, today=TODAY)) == ["companies_house:dissolved"]


def test_officer_matching_strips_titles_from_the_landlord_name() -> None:
    people = officers(director("CLARKE, Hannah Louise"))
    assert rule_officer_mismatch(subj(), people, "Mrs Hannah Clarke") is None
    assert rule_officer_mismatch(subj(), people, "Dr. Hannah Clarke") is None


def test_officer_matching_works_for_names_without_a_comma_and_with_initials() -> None:
    assert (
        rule_officer_mismatch(subj(), officers(director("Hannah Louise Clarke")), "Hannah Clarke")
        is None
    )
    assert (
        rule_officer_mismatch(subj(), officers(director("CLARKE, Hannah Louise")), "H Clarke")
        is None
    )
    mismatch = rule_officer_mismatch(
        subj(), officers(director("Hannah Louise Clarke")), "Sam Patel"
    )
    assert mismatch is not None


def test_officer_mismatch_is_skipped_when_the_landlord_name_is_missing_or_only_a_title() -> None:
    people = officers(director("CLARKE, Hannah Louise"))
    assert rule_officer_mismatch(subj(), people, None) is None
    assert rule_officer_mismatch(subj(), people, "") is None
    assert rule_officer_mismatch(subj(), people, "Mr") is None


def test_officer_mismatch_ignores_resigned_and_corporate_officers_when_matching() -> None:
    resigned = officers(
        director("PATEL, Sam", resigned_on="2020-01-01"), director("CLARKE, Hannah")
    )
    assert rule_officer_mismatch(subj(), resigned, "Sam Patel") is not None
    corporate = officers({"name": "PATEL, Sam", "officer_role": "corporate-director"})
    assert rule_officer_mismatch(subj(), corporate, "Sam Patel") is None  # no people to compare


def test_officer_mismatch_is_skipped_when_officers_are_paginated_beyond_the_fetched_page() -> None:
    page = officers(director("CLARKE, Hannah Louise"), active_count=150)
    assert page.complete is False
    assert rule_officer_mismatch(subj(), page, "Sam Patel") is None


def test_officer_mismatch_is_skipped_when_there_are_no_officers_to_compare() -> None:
    assert rule_officer_mismatch(subj(), None, "Sam Patel") is None
    assert rule_officer_mismatch(subj(), officers(), "Sam Patel") is None


def test_officer_search_name_flips_surname_first_names_and_passes_others_through() -> None:
    assert officer_search_name("CLARKE, Hannah Louise") == "Hannah Louise CLARKE"
    assert officer_search_name("Hannah Louise Clarke") == "Hannah Louise Clarke"


@pytest.mark.parametrize(
    ("officer_dob", "hit_dob", "expected"),
    [
        ({"month": 4, "year": 1985}, "1985-04-12", True),
        ({"month": 4, "year": 1985}, "1985-04", True),
        ({"month": 4, "year": 1985}, {"month": 4, "year": 1985}, True),
        ({"month": 4, "year": 1985}, "1985", True),
        ({"month": 4, "year": 1985}, "1985-09-12", False),
        ({"month": 4, "year": 1985}, "1971-04-12", False),
        (None, "1985-04-12", None),
        ({"month": 4, "year": 1985}, None, None),
        ({"month": 4, "year": 1985}, "not a date", None),
    ],
)
def test_dob_agrees_compares_year_and_month_and_returns_none_when_either_is_missing(
    officer_dob: Any, hit_dob: Any, expected: bool | None
) -> None:
    assert dob_agrees(officer_dob, hit_dob) is expected


def _officer(**extra: Any) -> Officer:
    return Officer.model_validate(director("CLARKE, Hannah Louise", **extra))


def test_disqualified_hit_with_matching_name_and_dob_counts() -> None:
    hit_ = DisqualifiedHit(title="Hannah Louise CLARKE", date_of_birth="1985-04-12")
    assert find_disqualified(_officer(date_of_birth={"month": 4, "year": 1985}), [hit_]) is hit_


def test_disqualified_hit_with_a_different_dob_is_ignored_even_with_an_exact_name() -> None:
    hit_ = DisqualifiedHit(title="Hannah Louise CLARKE", date_of_birth="1971-09-02")
    assert find_disqualified(_officer(date_of_birth={"month": 4, "year": 1985}), [hit_]) is None


def test_disqualified_hit_with_a_different_birth_month_is_ignored() -> None:
    hit_ = DisqualifiedHit(title="Hannah Louise CLARKE", date_of_birth="1985-09-02")
    assert find_disqualified(_officer(date_of_birth={"month": 4, "year": 1985}), [hit_]) is None


def test_disqualified_hit_without_a_dob_needs_an_exact_name_to_count() -> None:
    exact = DisqualifiedHit(title="Hannah Louise CLARKE")
    close = DisqualifiedHit(title="Hannah Louise CLARKES")  # scores 90+ but not 100
    assert find_disqualified(_officer(), [close]) is None
    assert find_disqualified(_officer(), [exact]) is exact


def test_disqualified_hit_with_a_close_name_counts_when_the_dobs_agree() -> None:
    close = DisqualifiedHit(title="Hannah Louise CLARKES", date_of_birth="1985-04-01")
    assert find_disqualified(_officer(date_of_birth={"month": 4, "year": 1985}), [close]) is close


def test_disqualified_hit_with_a_different_person_name_is_ignored() -> None:
    other = DisqualifiedHit(title="Peter James WRIGHT", date_of_birth="1985-04-01")
    assert find_disqualified(_officer(date_of_birth={"month": 4, "year": 1985}), [other]) is None


# --- name resolution (pure) ------------------------------------------------------------------


def test_rank_hits_resolves_one_strong_hit_with_a_clear_gap() -> None:
    hits = [hit("LARKFIELD & CO LETTINGS LTD", "09123456"), hit("ZENITH ROOFING LTD", "08000004")]
    decision = rank_hits("Larkfield & Co Lettings Ltd", hits)
    assert decision.kind == "resolved"
    assert decision.hit is not None and decision.hit.company_number == "09123456"


def test_rank_hits_resolves_one_exact_match_even_when_a_longer_name_also_scores_high() -> None:
    hits = [
        hit("ACME LETTINGS LIMITED", "00000010"),
        hit("ACME LETTINGS GROUP LIMITED", "00000011"),
    ]
    decision = rank_hits("Acme Lettings Ltd", hits)
    assert decision.kind == "resolved"
    assert decision.hit is not None and decision.hit.company_number == "00000010"


def test_rank_hits_is_ambiguous_for_two_strong_hits_within_five_points() -> None:
    hits = [hit("OAKWOOD HOME LETTING", "1"), hit("OAKWOOD HOMES LETTINGS", "2")]
    decision = rank_hits("Oakwood Home Lettings", hits)
    assert decision.kind == "ambiguous"
    assert {h.company_number for h in decision.candidates} == {"1", "2"}


def test_rank_hits_resolves_a_strong_best_hit_when_the_runner_up_is_five_points_behind() -> None:
    decision = rank_hits(
        "Oakwood Lettings Services",
        [hit("OAKWOOD LETTINGS SERVICE", "1"), hit("OAKWOOD LETTING", "2")],
    )
    assert decision.kind == "resolved"


def test_rank_hits_finds_none_when_nothing_reaches_ninety() -> None:
    assert rank_hits("Prime City Lettings", [hit("PRIMEVAL FARMS", "1")]).kind == "none"
    assert rank_hits("Prime City Lettings", []).kind == "none"


# --- I/O scenarios ---------------------------------------------------------------------------

GENUINE = "/company/09123456"


def genuine_routes(
    overrides: dict[tuple[str, str], Any] | None = None,
) -> dict[tuple[str, str], Any]:
    routes: dict[tuple[str, str], Any] = {
        ("GET", GENUINE): (200, load("company_active_old.json")),
        ("GET", f"{GENUINE}/officers"): (200, load("officers_larkfield.json")),
        ("GET", "/search/disqualified-officers"): (200, {"items": []}),
    }
    routes.update(overrides or {})
    return routes


def with_landlord(case: Case, **fields: Any) -> Case:
    out = case.model_copy(deep=True)
    assert out.landlord is not None
    for key, value in fields.items():
        setattr(out.landlord, key, value)
    return out


async def run_register(
    case: Case, routes: Router | dict, make_ctx
) -> tuple[RegisterResult, Router]:
    router = routes if isinstance(routes, Router) else Router(routes)
    ctx = await make_ctx(router)
    result = await register.run(ctx, case, today=TODAY, sleep=no_sleep)
    return result, router


async def test_first_request_carries_the_basic_auth_header(
    genuine_flat_case: Case, make_ctx
) -> None:
    _, router = await run_register(genuine_flat_case, genuine_routes(), make_ctx)
    expected = "Basic " + base64.b64encode(b"test-key:").decode()
    assert router.requests[0].headers["authorization"] == expected


async def test_genuine_flat_clears_with_registered_active_and_nothing_suspicious(
    genuine_flat_case: Case, make_ctx
) -> None:
    result, _ = await run_register(genuine_flat_case, genuine_routes(), make_ctx)
    assert not result.fatal and result.failed_checks == [] and result.questions == []
    assert ids(result.findings) == ["companies_house:registered-active"]
    assert [f for f in result.findings if f.supports == "suspicious"] == []
    assert result.facts == [
        Fact(
            key=FactKey.COMPANY_NUMBER,
            value="09123456",
            source="companies_house",
            agent="companies_house",
        )
    ]
    assert result.resolved_company is not None
    assert (result.resolved_company.number, result.resolved_company.matched_by) == (
        "09123456",
        "number",
    )


async def test_register_emits_no_address_or_landlord_name_facts(
    genuine_flat_case: Case, make_ctx
) -> None:
    result, _ = await run_register(genuine_flat_case, genuine_routes(), make_ctx)
    assert {f.key for f in result.facts} == {FactKey.COMPANY_NUMBER}


async def test_genuine_flat_director_hannah_louise_clarke_matches_landlord_hannah_clarke(
    genuine_flat_case: Case, make_ctx
) -> None:
    result, _ = await run_register(genuine_flat_case, genuine_routes(), make_ctx)
    assert "companies_house:officer-mismatch" not in ids(result.findings)


async def test_number_404_is_a_hard_flag_with_no_company_number_fact(
    genuine_flat_case: Case, make_ctx
) -> None:
    case = with_landlord(genuine_flat_case, company_number="00000001")
    result, router = await run_register(case, {("GET", "/company/00000001"): (404, "")}, make_ctx)
    flag = by_id(result.findings, "not-found")
    assert (flag.hard_flag, flag.severity, flag.check_id) == (
        True,
        Severity.CRITICAL,
        CheckId.LANDLORD_IDENTITY,
    )
    assert not result.fatal
    assert result.facts == []
    assert result.resolved_company is None
    assert len(router.requests) == 1  # a 404 is final: no retries, no officer calls


async def test_number_failing_with_500_three_times_is_fatal_not_a_not_found(
    genuine_flat_case: Case, make_ctx
) -> None:
    result, router = await run_register(genuine_flat_case, {("GET", GENUINE): (500, "")}, make_ctx)
    assert result.fatal is True
    assert result.error == "companies house: 500 after 3 attempts"
    assert result.findings == [] and result.facts == []
    assert len(router.calls(GENUINE)) == 3


async def test_number_failing_with_401_is_fatal_after_one_attempt(
    genuine_flat_case: Case, make_ctx
) -> None:
    result, router = await run_register(genuine_flat_case, {("GET", GENUINE): (401, "")}, make_ctx)
    assert result.fatal is True and (result.error or "").startswith("companies house: 401")
    assert len(router.requests) == 1


async def test_number_works_after_two_500s_because_the_third_attempt_succeeds(
    genuine_flat_case: Case, make_ctx
) -> None:
    routes = genuine_routes(
        {("GET", GENUINE): [(500, ""), (500, ""), (200, load("company_active_old.json"))]}
    )
    result, _ = await run_register(genuine_flat_case, routes, make_ctx)
    assert not result.fatal
    assert "companies_house:registered-active" in ids(result.findings)


async def test_short_number_is_zero_padded_in_the_request_and_in_the_fact(
    genuine_flat_case: Case, make_ctx
) -> None:
    case = with_landlord(genuine_flat_case, company_number="9123456")
    result, router = await run_register(case, genuine_routes(), make_ctx)
    assert router.requests[0].url.path == GENUINE
    assert result.facts[0].value == "09123456"


async def test_scottish_number_prefix_is_uppercased_and_not_padded(
    genuine_flat_case: Case, make_ctx
) -> None:
    case = with_landlord(genuine_flat_case, company_number="sc 123456", company_name=None)
    scottish = profile_dict(company_number="SC123456", company_name="THISTLE LETTINGS LTD")
    routes = {
        ("GET", "/company/SC123456"): (200, scottish),
        ("GET", "/company/SC123456/officers"): (200, {"items": []}),
    }
    result, router = await run_register(case, routes, make_ctx)
    assert router.requests[0].url.path == "/company/SC123456"
    assert result.facts[0].value == "SC123456"
    assert result.resolved_company is not None and result.resolved_company.number == "SC123456"


async def test_name_ambiguous_asks_for_the_number_and_never_fetches_a_company(
    fake_agency_case: Case, make_ctx
) -> None:
    case = with_landlord(fake_agency_case, company_name="Oakwood Lettings Ltd")
    routes = {("GET", "/search/companies"): (200, load("search_ambiguous.json"))}
    result, router = await run_register(case, routes, make_ctx)
    found = by_id(result.findings, "ambiguous-match")
    assert (found.severity, found.hard_flag) == (Severity.MEDIUM, False)
    assert result.questions == [register.ASK_FOR_NUMBER]
    assert result.resolved_company is None and result.facts == []
    assert router.calls("/company/") == []


async def test_name_with_no_close_hit_is_high_not_hard_and_asks_for_the_number(
    fake_agency_case: Case, make_ctx
) -> None:
    routes = {("GET", "/search/companies"): (200, load("search_no_match.json"))}
    result, router = await run_register(fake_agency_case, routes, make_ctx)
    found = by_id(result.findings, "name-no-match")
    assert (found.severity, found.hard_flag) == (Severity.HIGH, False)
    assert [f.hard_flag for f in result.findings] == [False]
    assert result.questions == [
        "Ask the agent for their company number (shown on their website and paperwork by law)."
    ]
    assert result.resolved_company is None and result.facts == [] and not result.fatal
    assert router.calls("/company/") == []


async def test_name_search_returning_nothing_at_all_is_a_no_match_not_a_failure(
    fake_agency_case: Case, make_ctx
) -> None:
    result, _ = await run_register(fake_agency_case, {}, make_ctx)  # every route 404s
    assert not result.fatal
    assert ids(result.findings) == ["companies_house:name-no-match"]


async def test_name_search_failing_with_500_is_fatal_and_emits_no_findings(
    fake_agency_case: Case, make_ctx
) -> None:
    result, router = await run_register(
        fake_agency_case, {("GET", "/search/companies"): (500, "")}, make_ctx
    )
    assert result.fatal is True
    assert result.error == "companies house: 500 after 3 attempts"
    assert result.findings == []
    assert len(router.calls("/search/companies")) == 3


async def test_profile_fetch_failing_after_a_name_match_is_fatal(
    fake_agency_case: Case, make_ctx
) -> None:
    routes = {
        ("GET", "/search/companies"): (200, load("search_prime_city.json")),
        ("GET", "/company/11223344"): (503, ""),
    }
    result, _ = await run_register(fake_agency_case, routes, make_ctx)
    assert result.fatal is True and (result.error or "").startswith("companies house: 503")
    assert result.findings == []


async def test_fake_agency_resolved_by_name_to_a_dissolved_company_raises_the_hard_flag(
    fake_agency_case: Case, make_ctx
) -> None:
    routes = {
        ("GET", "/search/companies"): (200, load("search_prime_city.json")),
        ("GET", "/company/11223344"): (200, load("company_dissolved.json")),
    }
    result, router = await run_register(fake_agency_case, routes, make_ctx)
    flag = by_id(result.findings, "dissolved")
    assert (flag.hard_flag, flag.severity, flag.check_id) == (
        True,
        Severity.CRITICAL,
        CheckId.LANDLORD_IDENTITY,
    )
    assert result.resolved_company is not None
    assert result.resolved_company.matched_by == "name"
    assert result.facts[0].value == "11223344"
    assert router.calls("/company/11223344/officers") == []  # dead: extras skipped
    assert "companies_house:registered-active" not in ids(result.findings)


async def test_student_message_naming_the_company_becomes_a_second_evidence_ref(
    fake_agency_case: Case, make_ctx
) -> None:
    case = fake_agency_case.model_copy(deep=True)
    case.messages[1].text += " We are Prime City Lettings Ltd, fully registered."
    routes = {
        ("GET", "/search/companies"): (200, load("search_prime_city.json")),
        ("GET", "/company/11223344"): (200, load("company_dissolved.json")),
    }
    result, _ = await run_register(case, routes, make_ctx)
    refs = by_id(result.findings, "dissolved").evidence
    assert [e.evidence_id for e in refs] == ["companies_house", case.messages[1].evidence_id]
    quote = refs[1].quote or ""
    assert "Prime City Lettings Ltd" in quote
    assert quote in case.messages[1].text


async def test_negotiator_sam_patel_gets_a_medium_officer_mismatch_that_cannot_flip_the_check(
    genuine_flat_case: Case, make_ctx
) -> None:
    case = with_landlord(genuine_flat_case, name="Sam Patel")
    result, _ = await run_register(case, genuine_routes(), make_ctx)
    mismatch = by_id(result.findings, "officer-mismatch")
    assert (mismatch.severity, mismatch.confidence) == (Severity.MEDIUM, 0.5)
    strong = [
        f
        for f in result.findings
        if f.supports == "suspicious"
        and f.severity in (Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)
        and f.confidence >= 0.6
    ]
    assert strong == []
    assert "companies_house:registered-active" in ids(result.findings)  # company still genuine


async def test_landlord_without_a_name_skips_officer_matching(
    genuine_flat_case: Case, make_ctx
) -> None:
    case = with_landlord(genuine_flat_case, name=None)
    result, _ = await run_register(case, genuine_routes(), make_ctx)
    assert "companies_house:officer-mismatch" not in ids(result.findings)
    assert "companies_house:registered-active" in ids(result.findings)


async def test_young_company_at_a_virtual_office_gets_medium_and_low_findings_and_no_clear(
    genuine_flat_case: Case, make_ctx
) -> None:
    case = with_landlord(genuine_flat_case, company_number="15551234", company_name=None)
    routes = {("GET", "/company/15551234"): (200, load("company_young.json"))}
    result, _ = await run_register(case, routes, make_ctx)
    young = by_id(result.findings, "young-company")
    virtual = by_id(result.findings, "virtual-office")
    assert (young.severity, virtual.severity) == (Severity.MEDIUM, Severity.LOW)
    assert sorted(ids(result.findings)) == [
        "companies_house:virtual-office",
        "companies_house:young-company",
    ]
    assert [f for f in result.findings if f.supports == "cleared"] == []


async def test_number_with_a_different_company_name_flags_the_mismatch_and_does_not_clear(
    genuine_flat_case: Case, make_ctx
) -> None:
    case = with_landlord(genuine_flat_case, company_name="Prime City Lettings Ltd")
    result, _ = await run_register(case, genuine_routes(), make_ctx)
    mismatch = by_id(result.findings, "name-number-mismatch")
    assert (mismatch.severity, mismatch.confidence, mismatch.hard_flag) == (
        Severity.HIGH,
        0.9,
        False,
    )
    assert (
        "The company number belongs to LARKFIELD & CO LETTINGS LTD, not Prime City Lettings Ltd."
        in (mismatch.detail)
    )
    assert "companies_house:registered-active" not in ids(result.findings)


async def test_officers_failing_leaves_the_profile_findings_and_notes_a_failed_check(
    genuine_flat_case: Case, make_ctx
) -> None:
    case = with_landlord(genuine_flat_case, name="Sam Patel")
    routes = genuine_routes({("GET", f"{GENUINE}/officers"): (500, "")})
    result, router = await run_register(case, routes, make_ctx)
    assert not result.fatal
    assert result.failed_checks == ["officers (Companies House: 500 after 3 attempts)"]
    assert ids(result.findings) == ["companies_house:registered-active"]  # no officer finding
    assert len(router.calls(f"{GENUINE}/officers")) == 3
    assert router.calls("/search/disqualified-officers") == []


async def test_officers_404_means_no_officers_listed_and_is_not_a_failed_check(
    genuine_flat_case: Case, make_ctx
) -> None:
    case = with_landlord(genuine_flat_case, name="Sam Patel")
    routes = genuine_routes({("GET", f"{GENUINE}/officers"): (404, "")})
    result, _ = await run_register(case, routes, make_ctx)
    assert result.failed_checks == []
    assert "companies_house:officer-mismatch" not in ids(result.findings)


async def test_paginated_officers_never_claim_the_person_is_not_an_officer(
    genuine_flat_case: Case, make_ctx
) -> None:
    case = with_landlord(genuine_flat_case, name="Sam Patel")
    routes = genuine_routes(
        {("GET", f"{GENUINE}/officers"): (200, load("officers_paginated.json"))}
    )
    result, _ = await run_register(case, routes, make_ctx)
    assert "companies_house:officer-mismatch" not in ids(result.findings)


async def test_disqualified_hit_with_a_matching_dob_adds_a_high_finding_and_queries_forenames_first(
    genuine_flat_case: Case, make_ctx
) -> None:
    routes = genuine_routes(
        {("GET", "/search/disqualified-officers"): (200, load("disqualified_clarke_match.json"))}
    )
    result, router = await run_register(genuine_flat_case, routes, make_ctx)
    flag = by_id(result.findings, "disqualified-director")
    assert (flag.severity, flag.hard_flag) == (Severity.HIGH, False)
    queries = [r.url.params["q"] for r in router.calls("/search/disqualified-officers")]
    assert queries == ["Hannah Louise CLARKE"]  # only the active person, not the corporate officer


async def test_disqualified_hit_with_a_different_birth_year_adds_no_finding(
    genuine_flat_case: Case, make_ctx
) -> None:
    routes = genuine_routes(
        {
            ("GET", "/search/disqualified-officers"): (
                200,
                load("disqualified_clarke_other_dob.json"),
            )
        }
    )
    result, _ = await run_register(genuine_flat_case, routes, make_ctx)
    assert "companies_house:disqualified-director" not in ids(result.findings)


async def test_disqualified_hit_without_a_dob_and_an_exact_name_still_counts(
    genuine_flat_case: Case, make_ctx
) -> None:
    routes = genuine_routes(
        {("GET", "/search/disqualified-officers"): (200, load("disqualified_clarke_no_dob.json"))}
    )
    result, _ = await run_register(genuine_flat_case, routes, make_ctx)
    assert "companies_house:disqualified-director" in ids(result.findings)


async def test_disqualified_lookup_failure_is_non_fatal_and_keeps_the_other_findings(
    genuine_flat_case: Case, make_ctx
) -> None:
    routes = genuine_routes({("GET", "/search/disqualified-officers"): (500, "")})
    result, _ = await run_register(genuine_flat_case, routes, make_ctx)
    assert not result.fatal
    assert result.failed_checks == ["disqualified officers (Companies House: 500 after 3 attempts)"]
    assert "companies_house:registered-active" in ids(result.findings)


async def test_at_most_three_officers_are_looked_up_for_disqualification(
    genuine_flat_case: Case, make_ctx
) -> None:
    five = {"items": [director(f"SURNAME{i}, Person") for i in range(5)]}
    routes = genuine_routes({("GET", f"{GENUINE}/officers"): (200, five)})
    _, router = await run_register(genuine_flat_case, routes, make_ctx)
    assert len(router.calls("/search/disqualified-officers")) == 3


async def test_voluntary_arrangement_company_is_not_treated_as_dead_in_a_full_run(
    genuine_flat_case: Case, make_ctx
) -> None:
    cva = profile_dict(company_status="voluntary-arrangement")
    result, _ = await run_register(
        genuine_flat_case, genuine_routes({("GET", GENUINE): (200, cva)}), make_ctx
    )
    assert "companies_house:dissolved" not in ids(result.findings)
    assert [f for f in result.findings if f.hard_flag] == []
    assert "companies_house:registered-active" not in ids(result.findings)


async def test_petition_to_restore_dissolved_gives_strike_off_proposed_in_a_full_run(
    genuine_flat_case: Case, make_ctx
) -> None:
    detail = profile_dict(company_status_detail="petition-to-restore-dissolved")
    result, _ = await run_register(
        genuine_flat_case, genuine_routes({("GET", GENUINE): (200, detail)}), make_ctx
    )
    assert "companies_house:strike-off-proposed" in ids(result.findings)
    assert "companies_house:registered-active" not in ids(result.findings)


async def test_landlord_with_neither_name_nor_number_makes_no_requests(
    genuine_flat_case: Case, make_ctx
) -> None:
    case = with_landlord(genuine_flat_case, company_name=None, company_number=None)
    result, router = await run_register(case, {}, make_ctx)
    assert result.findings == [] and result.facts == [] and router.requests == []


async def test_run_defaults_today_to_the_real_date_when_not_given(
    genuine_flat_case: Case, make_ctx
) -> None:
    ctx = await make_ctx(genuine_routes())
    result = await register.run(ctx, genuine_flat_case, sleep=no_sleep)
    assert "companies_house:registered-active" in ids(result.findings)


# --- invariants over every finding the module can produce ------------------------------------


async def _scenario_findings(genuine: Case, agency: Case, make_ctx) -> list[Finding]:
    found: list[Finding] = []
    sam = with_landlord(genuine, name="Sam Patel")
    mismatch_case = with_landlord(genuine, company_name="Prime City Lettings Ltd")
    young_case = with_landlord(genuine, company_number="15551234", company_name=None)
    not_found_case = with_landlord(genuine, company_number="00000001")
    dq_routes = genuine_routes(
        {("GET", "/search/disqualified-officers"): (200, load("disqualified_clarke_match.json"))}
    )
    messy = profile_dict(
        company_status_detail="active-proposal-to-strike-off",
        has_insolvency_history=True,
        sic_codes=["47190"],
        accounts={"overdue": True, "last_accounts": {"type": "dormant"}},
        confirmation_statement={"overdue": True},
        registered_office_address={"address_line_1": "20-22 Wenlock Road", "locality": "London"},
        date_of_creation="2026-09-01",
    )
    runs: list[tuple[Case, Any]] = [
        (genuine, genuine_routes()),
        (sam, genuine_routes()),
        (genuine, dq_routes),
        (mismatch_case, genuine_routes()),
        (young_case, {("GET", "/company/15551234"): (200, load("company_young.json"))}),
        (not_found_case, {("GET", "/company/00000001"): (404, "")}),
        (genuine, genuine_routes({("GET", GENUINE): (200, messy)})),
        (
            agency,
            {
                ("GET", "/search/companies"): (200, load("search_prime_city.json")),
                ("GET", "/company/11223344"): (200, load("company_dissolved.json")),
            },
        ),
        (agency, {("GET", "/search/companies"): (200, load("search_no_match.json"))}),
        (
            with_landlord(agency, company_name="Oakwood Lettings Ltd"),
            {("GET", "/search/companies"): (200, load("search_ambiguous.json"))},
        ),
    ]
    for case, routes in runs:
        result, _ = await run_register(case, deepcopy(routes), make_ctx)
        found.extend(result.findings)
    return found


async def test_every_finding_is_quoted_cited_and_only_not_found_and_dissolved_are_hard(
    genuine_flat_case: Case, fake_agency_case: Case, make_ctx
) -> None:
    findings = await _scenario_findings(genuine_flat_case, fake_agency_case, make_ctx)
    assert {f.id.split(":", 1)[1] for f in findings} >= {
        "not-found",
        "dissolved",
        "name-no-match",
        "ambiguous-match",
        "young-company",
        "officer-mismatch",
        "disqualified-director",
        "overdue-filings",
        "dormant",
        "insolvency-history",
        "non-property-sic",
        "virtual-office",
        "registered-active",
        "name-number-mismatch",
        "strike-off-proposed",
    }
    for f in findings:
        assert f.id.startswith("companies_house:")
        assert f.agent == "companies_house"
        assert f.check_id == CheckId.LANDLORD_IDENTITY
        assert f.evidence, f.id
        assert all(isinstance(e, EvidenceRef) and (e.quote or "").strip() for e in f.evidence), f.id
        assert "Source: http" in f.detail, f.id
        assert f.hard_flag == (f.id in {"companies_house:not-found", "companies_house:dissolved"})
    assert {f.id for f in findings if f.supports == "cleared"} == {
        "companies_house:registered-active"
    }
