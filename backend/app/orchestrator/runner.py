"""Select, run in parallel, time out and hash-skip agents."""

import asyncio
import time
from collections.abc import Awaitable, Callable

from app.contracts import (
    AgentFinished,
    AgentReport,
    AgentStarted,
    AgentStatus,
    Case,
    StreamEvent,
)
from app.core.agent import AgentContext, BaseAgent, has_need, hash_slice

Publish = Callable[[StreamEvent], Awaitable[None]]


async def run_agents(
    case: Case, agents: list[BaseAgent], ctx: AgentContext, publish: Publish
) -> dict[str, AgentReport]:
    """Run every agent whose inputs are present and changed. Never raises."""
    results: dict[str, AgentReport] = {}
    scheduled: list[BaseAgent] = []
    for agent in agents:
        missing = [n.value for n in agent.requires if not has_need(case, n)]
        if missing:
            results[agent.name] = agent.report(
                case, status=AgentStatus.SKIPPED, error=f"missing: {', '.join(missing)}"
            )
            continue
        previous = case.reports.get(agent.name)
        current_hash = hash_slice(agent.input_slice(case))
        if previous and previous.status == AgentStatus.OK and previous.input_hash == current_hash:
            continue
        scheduled.append(agent)

    async def run_one(agent: BaseAgent) -> AgentReport:
        await publish(AgentStarted(agent=agent.name))
        started = time.perf_counter()
        try:
            report = await asyncio.wait_for(agent.run(case, ctx), timeout=agent.timeout_s)
        except TimeoutError:
            report = agent.report(case, status=AgentStatus.ERROR, error="timeout")
        except Exception as exc:  # noqa: BLE001 - one agent must never break the run
            ctx.log.exception("agent %s failed", agent.name)
            report = agent.report(case, status=AgentStatus.ERROR, error=repr(exc))
        report = report.model_copy(
            update={"duration_ms": int((time.perf_counter() - started) * 1000)}
        )
        await publish(AgentFinished(report=report))
        return report

    for report in await asyncio.gather(*(run_one(a) for a in scheduled)):
        results[report.agent] = report
    return results
