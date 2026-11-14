import asyncio

from app.contracts import AgentReport, AgentStatus, Case, StreamEvent
from app.core.agent import AgentContext, BaseAgent, Need
from app.orchestrator.runner import run_agents


class _Counting(BaseAgent):
    name = "counting"
    requires = frozenset({Need.MESSAGES})

    def __init__(self) -> None:
        self.runs = 0

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        self.runs += 1
        return self.report(case)


class _Raising(BaseAgent):
    name = "raising"

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        raise RuntimeError("boom")


class _Slow(BaseAgent):
    name = "slow"
    timeout_s = 0.05

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        await asyncio.sleep(2)
        return self.report(case)


class _Events:
    def __init__(self) -> None:
        self.events: list[StreamEvent] = []

    async def __call__(self, event: StreamEvent) -> None:
        self.events.append(event)


async def test_missing_needs_give_skipped(fake_agency_case: Case, ctx: AgentContext) -> None:
    case = fake_agency_case.model_copy(update={"messages": []})
    agent = _Counting()
    results = await run_agents(case, [agent], ctx, _Events())
    assert results["counting"].status == AgentStatus.SKIPPED
    assert results["counting"].error == "missing: messages"
    assert agent.runs == 0


async def test_unchanged_input_is_not_rerun(fake_agency_case: Case, ctx: AgentContext) -> None:
    agent = _Counting()
    first = await run_agents(fake_agency_case, [agent], ctx, _Events())
    assert agent.runs == 1 and first["counting"].status == AgentStatus.OK

    case = fake_agency_case.model_copy(update={"reports": first})
    assert await run_agents(case, [agent], ctx, _Events()) == {}
    assert agent.runs == 1

    changed = case.model_copy(update={"messages": case.messages[:-1]})
    again = await run_agents(changed, [agent], ctx, _Events())
    assert "counting" in again and agent.runs == 2


async def test_failing_agent_gives_error_and_others_finish(
    fake_agency_case: Case, ctx: AgentContext
) -> None:
    good = _Counting()
    events = _Events()
    results = await run_agents(fake_agency_case, [_Raising(), good], ctx, events)
    assert results["raising"].status == AgentStatus.ERROR
    assert "boom" in (results["raising"].error or "")
    assert results["counting"].status == AgentStatus.OK
    assert [e.type for e in events.events].count("agent_started") == 2
    assert [e.type for e in events.events].count("agent_finished") == 2


async def test_slow_agent_times_out(fake_agency_case: Case, ctx: AgentContext) -> None:
    results = await run_agents(fake_agency_case, [_Slow(), _Counting()], ctx, _Events())
    assert results["slow"].status == AgentStatus.ERROR
    assert results["slow"].error == "timeout"
    assert results["counting"].status == AgentStatus.OK
