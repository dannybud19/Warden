"""VideoAnalysis agent. Phase 0: returns an empty OK report."""

from app.contracts import AgentReport, Case
from app.core.agent import AgentContext, BaseAgent, Need


class VideoAnalysisAgent(BaseAgent):
    name = "video_analysis"
    requires = frozenset({Need.VIDEO})

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        # TODO(Bill, later): real implementation. See plan.md section 13.
        return self.report(case, questions=[])
