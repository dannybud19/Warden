"""ContractChecker agent. Phase 0: returns an empty OK report."""

from app.contracts import AgentReport, Case
from app.core.agent import AgentContext, BaseAgent, Need


class ContractCheckerAgent(BaseAgent):
    name = "contract_checker"
    requires = frozenset({Need.CONTRACT})

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        # TODO(Bill, WS G): real implementation. See plan.md section 14, WS G.
        return self.report(case, questions=[])
