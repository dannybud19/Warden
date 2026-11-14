"""EmotionClassifier agent. Phase 0: returns an empty OK report."""

from app.contracts import AgentReport, Case
from app.core.agent import AgentContext, BaseAgent, Need


class EmotionClassifierAgent(BaseAgent):
    name = "emotion_classifier"
    requires = frozenset({Need.MESSAGES})

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        # TODO(Georgi, WS E): real implementation. See plan.md section 14, WS E.
        return self.report(case, questions=[])
