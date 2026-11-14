from app.agents.contract_checker.agent import ContractCheckerAgent
from app.agents.contract_checker.stub import ContractCheckerStub
from app.contracts import AgentReport, AgentStatus, Case
from app.core.agent import AgentContext, hash_slice


async def test_stub_returns_valid_report(fake_agency_case: Case, ctx: AgentContext) -> None:
    agent = ContractCheckerStub()
    report = await agent.run(fake_agency_case, ctx)
    assert AgentReport.model_validate(report.model_dump()) == report
    assert report.agent == "contract_checker"
    assert report.version.endswith("-stub")
    assert report.input_hash == hash_slice(agent.input_slice(fake_agency_case))


async def test_real_agent_runs_with_fakes(fake_agency_case: Case, ctx: AgentContext) -> None:
    report = await ContractCheckerAgent().run(fake_agency_case, ctx)
    assert report.status == AgentStatus.NEEDS_INPUT
    assert report.agent == "contract_checker"
    assert report.findings and report.questions
    assert all(not finding.hard_flag for finding in report.findings)
