"""MessageChecker: scam signals in the chat and email messages. Rules first, one LLM pass second."""

from app.agents.message_checker.llm import LLMResult, extra_findings
from app.agents.message_checker.rules import reconcile, run_rules
from app.contracts import AgentReport, Case, Fact
from app.core.agent import AgentContext, BaseAgent, Need


def merge_facts(rule_facts: list[Fact], llm_facts: list[Fact]) -> list[Fact]:
    """Rule facts win: a model fact is only added for a key the rules found nothing for."""
    keys = {f.key for f in rule_facts}
    return rule_facts + [f for f in llm_facts if f.key not in keys]


class MessageCheckerAgent(BaseAgent):
    name = "message_checker"
    version = "0.3.0"
    requires = frozenset({Need.MESSAGES})

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        rules = run_rules(case)
        try:
            llm = await extra_findings(case, rules.fired, ctx)
        except Exception as exc:  # noqa: BLE001 - the rules must still report if the model fails
            ctx.log.warning("message_checker: LLM pass failed, rules only (%r)", exc)
            llm = LLMResult()
        return self.report(
            case,
            findings=reconcile(rules.findings + llm.findings),
            facts=merge_facts(rules.facts, llm.facts),
            questions=llm.questions,
        )
