from app.agents.message_checker.agent import MessageCheckerAgent
from app.agents.message_checker.stub import MessageCheckerStub
from app.contracts import AgentReport, AgentStatus, Case
from app.core.agent import AgentContext, hash_slice


async def test_stub_returns_valid_report(fake_agency_case: Case, ctx: AgentContext) -> None:
    agent = MessageCheckerStub()
    report = await agent.run(fake_agency_case, ctx)
    assert AgentReport.model_validate(report.model_dump()) == report
    assert report.agent == "message_checker"
    assert report.version.endswith("-stub")
    assert report.input_hash == hash_slice(agent.input_slice(fake_agency_case))


async def test_real_agent_runs_with_fakes(fake_agency_case: Case, ctx: AgentContext) -> None:
    report = await MessageCheckerAgent().run(fake_agency_case, ctx)
    assert report.status == AgentStatus.OK
    assert report.agent == "message_checker"
