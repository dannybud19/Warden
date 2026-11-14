"""MessageChecker agent. Phase 0: returns an empty OK report."""

from app.contracts import AgentReport, Case
from app.core.agent import AgentContext, BaseAgent, Need


class MessageCheckerAgent(BaseAgent):
    name = "message_checker"
    requires = frozenset({Need.MESSAGES})

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        # TODO(Georgi, WS D): real implementation. See plan.md section 14, WS D.
        return self.report(case, questions=[])
