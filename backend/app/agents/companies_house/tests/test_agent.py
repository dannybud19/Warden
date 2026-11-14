"""Agent shell tests (Phase 1). Phase 3 extends this with the full Appendix F scenarios."""

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


async def test_skeleton_run_is_ok_and_empty(genuine_flat_case: Case, make_ctx) -> None:
    report = await CompaniesHouseAgent(sleep=no_sleep).run(genuine_flat_case, await make_ctx())
    assert report.status == AgentStatus.OK
    assert report.agent == "companies_house"


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
