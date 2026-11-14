"""Property module tests: postcodes.io is mocked, nothing touches the network or sleeps."""

from collections.abc import Awaitable, Callable

import pytest

from app.agents.companies_house.constants import CONF, EV_POSTCODES
from app.agents.companies_house.modules import property as prop
from app.agents.companies_house.testing import Router, fixture_json, no_sleep
from app.contracts import Case, Category, CheckId, Listing, Message, Severity
from app.core.agent import AgentContext

MakeCtx = Callable[..., Awaitable[AgentContext]]

OK = (200, fixture_json("property", "postcode_ok.json"))
NULL_DISTRICT = (200, fixture_json("property", "postcode_null_district.json"))
NOT_FOUND = (404, fixture_json("property", "postcode_not_found.json"))
PATH = "/postcodes/SE17LP"


def _case(base: Case, **listing: object) -> Case:
    data = base.listing.model_dump() if base.listing else {}
    data.update(listing)
    return base.model_copy(update={"listing": Listing(**data)})


async def _run(make_ctx: MakeCtx, case: Case, reply: object) -> tuple[prop.ModuleResult, Router]:
    router = Router({("GET", "/postcodes/"): reply})  # type: ignore[dict-item]
    ctx = await make_ctx(router)
    return await prop.run(ctx, case, sleep=no_sleep), router


# --- pure area logic --------------------------------------------------------------------------


def test_claimed_areas_finds_named_borough_case_insensitively() -> None:
    assert prop.claimed_areas("Lovely flat in HACKNEY near the park") == ["Hackney"]


def test_claimed_areas_ignores_borough_name_used_as_street() -> None:
    assert prop.claimed_areas("12 Harrow Road, London W9") == []


def test_area_mismatch_none_when_listing_names_no_area() -> None:
    assert prop.area_mismatch("Flat 5, 21 Mercer Street, London SE1 7LP", "Southwark") is None


def test_area_mismatch_returns_claimed_area_when_different() -> None:
    assert prop.area_mismatch("Bright flat in Camden", "Southwark") == "Camden"


def test_area_mismatch_none_when_one_named_area_matches() -> None:
    assert prop.area_mismatch("Between Camden and Southwark", "Southwark") is None


def test_area_mismatch_strips_london_borough_prefix() -> None:
    assert prop.area_mismatch("Nice flat in Southwark", "London Borough of Southwark") is None


def test_area_mismatch_treats_westminster_forms_as_equal() -> None:
    assert prop.area_mismatch("Flat in Westminster", "City of Westminster") is None


def test_area_mismatch_city_of_london_equals_itself_but_not_a_borough() -> None:
    assert prop.area_mismatch("Office in the City of London", "City of London") is None
    assert prop.area_mismatch("Office in the City of London", "Islington") == "City of London"


def test_area_mismatch_none_when_district_null() -> None:
    assert prop.area_mismatch("Flat in Camden", None) is None


# --- run --------------------------------------------------------------------------------------


async def test_unknown_postcode_gives_medium_postcode_invalid_with_approved_wording(
    make_ctx: MakeCtx, genuine_flat_case: Case
) -> None:
    result, router = await _run(make_ctx, genuine_flat_case, NOT_FOUND)
    assert [f.id for f in result.findings] == ["companies_house:postcode-invalid"]
    f = result.findings[0]
    assert f.severity == Severity.MEDIUM
    assert f.confidence == CONF["postcode-invalid"] == 0.8
    assert f.category == Category.PROPERTY
    assert f.check_id == CheckId.LANDLORD_IDENTITY
    assert f.title == "The listing's postcode doesn't exist"
    assert f.detail.startswith(
        "This postcode wasn't found in the national postcode list. "
        "Very new addresses can be missing, so double-check it."
    )
    assert "SE1 7LP" in f.detail
    assert f"Source: https://api.postcodes.io{PATH}" in f.detail
    assert f.evidence[0].evidence_id == EV_POSTCODES
    assert f.evidence[0].quote == "postcode: SE1 7LP (not found)"
    assert not f.hard_flag
    assert result.failed_checks == []
    assert len(router.requests) == 1


async def test_unknown_postcode_also_quotes_students_own_message(
    make_ctx: MakeCtx, genuine_flat_case: Case
) -> None:
    msg = Message(
        id="m-pc",
        evidence_id="ev-pc",
        sender="agent",
        channel="whatsapp",
        text="The flat is at 21 Mercer Street, SE1 7LP, viewing any time.",
    )
    case = genuine_flat_case.model_copy(update={"messages": [msg]})
    result, _ = await _run(make_ctx, case, NOT_FOUND)
    refs = result.findings[0].evidence
    assert [r.evidence_id for r in refs] == [EV_POSTCODES, "ev-pc"]
    assert "SE1 7LP" in (refs[1].quote or "")


async def test_no_listing_skips_silently_with_zero_requests(
    make_ctx: MakeCtx, genuine_flat_case: Case
) -> None:
    case = genuine_flat_case.model_copy(update={"listing": None})
    result, router = await _run(make_ctx, case, OK)
    assert result.findings == [] and result.failed_checks == []
    assert router.requests == []


async def test_listing_without_any_postcode_skips_with_zero_requests(
    make_ctx: MakeCtx, genuine_flat_case: Case
) -> None:
    case = _case(genuine_flat_case, postcode=None, address="Flat 5, Mercer Street, London")
    result, router = await _run(make_ctx, case, OK)
    assert result.findings == [] and result.failed_checks == []
    assert router.requests == []


async def test_postcode_in_address_text_is_normalised_before_the_call(
    make_ctx: MakeCtx, genuine_flat_case: Case
) -> None:
    case = _case(genuine_flat_case, postcode=None, address="5 mercer street london se17lp")
    result, router = await _run(make_ctx, case, OK)
    assert [r.url.path for r in router.requests] == [PATH]
    assert result.findings == []


async def test_valid_postcode_and_no_area_named_gives_no_finding(
    make_ctx: MakeCtx, genuine_flat_case: Case
) -> None:
    result, _ = await _run(make_ctx, genuine_flat_case, OK)
    assert result.findings == [] and result.failed_checks == []


async def test_listing_naming_a_different_borough_gives_low_area_mismatch(
    make_ctx: MakeCtx, genuine_flat_case: Case
) -> None:
    case = _case(genuine_flat_case, description="Lovely flat in Camden, close to everything")
    result, _ = await _run(make_ctx, case, OK)
    assert [f.id for f in result.findings] == ["companies_house:postcode-area-mismatch"]
    f = result.findings[0]
    assert f.severity == Severity.LOW
    assert f.confidence == CONF["postcode-area-mismatch"] == 0.5
    assert f.category == Category.PROPERTY
    assert "SE1 7LP is in Southwark, not Camden as the listing says." in f.detail
    assert "Source: https://api.postcodes.io" in f.detail
    assert f.evidence[0].quote == "admin_district: Southwark"


async def test_listing_naming_the_same_borough_gives_no_finding(
    make_ctx: MakeCtx, genuine_flat_case: Case
) -> None:
    case = _case(genuine_flat_case, description="Lovely flat in Southwark")
    result, _ = await _run(make_ctx, case, OK)
    assert result.findings == []


async def test_null_admin_district_gives_no_finding(
    make_ctx: MakeCtx, genuine_flat_case: Case
) -> None:
    case = _case(genuine_flat_case, description="Lovely flat in Camden")
    result, _ = await _run(make_ctx, case, NULL_DISTRICT)
    assert result.findings == [] and result.failed_checks == []


async def test_server_errors_after_retries_fail_the_check_and_never_flag_invalid(
    make_ctx: MakeCtx, genuine_flat_case: Case
) -> None:
    result, router = await _run(make_ctx, genuine_flat_case, (500, ""))
    assert result.findings == []
    assert len(result.failed_checks) == 1
    assert result.failed_checks[0].startswith("postcode lookup (postcodes.io: ")
    assert len(router.requests) == 3


async def test_forbidden_response_fails_the_check_and_never_flags_invalid(
    make_ctx: MakeCtx, genuine_flat_case: Case
) -> None:
    result, _ = await _run(make_ctx, genuine_flat_case, (403, ""))
    assert result.findings == []
    assert len(result.failed_checks) == 1


async def test_malformed_200_body_fails_the_check(
    make_ctx: MakeCtx, genuine_flat_case: Case
) -> None:
    result, _ = await _run(make_ctx, genuine_flat_case, (200, "<html>not json</html>"))
    assert result.findings == []
    assert result.failed_checks == ["postcode lookup (postcodes.io: malformed response)"]


@pytest.mark.parametrize("which", ["invalid", "mismatch"])
async def test_every_finding_upholds_the_evidence_invariants(
    make_ctx: MakeCtx, genuine_flat_case: Case, which: str
) -> None:
    if which == "invalid":
        result, _ = await _run(make_ctx, genuine_flat_case, NOT_FOUND)
        expected = (Severity.MEDIUM, 0.8)
    else:
        case = _case(genuine_flat_case, description="Flat in Camden")
        result, _ = await _run(make_ctx, case, OK)
        expected = (Severity.LOW, 0.5)
    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.id.startswith("companies_house:")
    assert f.evidence and all(r.quote and r.quote.strip() for r in f.evidence)
    assert "\nSource: https://" in f.detail
    assert f.hard_flag is False
    assert f.supports == "suspicious"
    assert (f.severity, f.confidence) == expected
    assert result.facts == []
