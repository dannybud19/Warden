from dataclasses import replace

from app.agents.companies_house.agent import CompaniesHouseAgent
from app.agents.companies_house.stub import CompaniesHouseStub
from app.agents.companies_house.testing import no_sleep
from app.contracts import AgentReport, AgentStatus, Case
from app.core.agent import AgentContext, hash_slice
from app.core.settings import Settings


async def test_stub_returns_valid_report(fake_agency_case: Case, ctx: AgentContext) -> None:
    agent = CompaniesHouseStub()
    report = await agent.run(fake_agency_case, ctx)
    assert AgentReport.model_validate(report.model_dump()) == report
    assert report.agent == "companies_house"
    assert report.version.endswith("-stub")
    assert report.input_hash == hash_slice(agent.input_slice(fake_agency_case))


async def test_real_agent_runs_with_fakes(
    fake_agency_case: Case, ctx: AgentContext, ch_settings: Settings
) -> None:
    # NOTE: the real agent refuses to run without a Companies House key (plan App. D), so give the
    # shared 404-only ctx one. The name search then gets 404 = zero hits, which is still status ok.
    ctx = replace(ctx, settings=ch_settings)
    report = await CompaniesHouseAgent(sleep=no_sleep).run(fake_agency_case, ctx)
    assert report.status == AgentStatus.OK
    assert report.agent == "companies_house"
