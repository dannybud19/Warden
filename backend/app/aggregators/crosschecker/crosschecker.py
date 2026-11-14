"""Cross-checker stub: passes the rule findings through and writes a template recap.

The orchestrator computes the rule findings (`orchestrator.crosscheck.compare`) and passes them in,
because aggregators may not import the orchestrator. The LLM version (WS J) replaces `review` and
keeps its signature.
"""

from app.contracts import AgentReport, Case, Finding
from app.core.agent import AgentContext

NAME = "crosscheck"
VERSION = "0.1.0"


async def review(case: Case, rule_findings: list[Finding], ctx: AgentContext) -> AgentReport:
    """The report stored as `case.reports["crosscheck"]`, with the recap in `summary`."""
    raise NotImplementedError


def recap(findings: list[Finding]) -> str | None:
    """One or two plain sentences naming what the sources disagree on; None when nothing does."""
    raise NotImplementedError
