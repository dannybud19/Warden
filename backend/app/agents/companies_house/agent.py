"""CompaniesHouse agent. Phase 0: returns an empty OK report."""

from app.contracts import AgentReport, Case
from app.core.agent import AgentContext, BaseAgent, Need


class CompaniesHouseAgent(BaseAgent):
    name = "companies_house"
    requires = frozenset({Need.LANDLORD})

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        # TODO(Danny, WS B): real implementation. See plan.md section 14, WS B.
        return self.report(case, questions=[])
