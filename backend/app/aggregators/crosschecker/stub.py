"""Stub mode: the rule findings and their template recap, no LLM.

Unlike the checker agents' stubs, this replays no fixture: canned consistency findings would cite
evidence ids that do not exist in a real case.
"""

from app.aggregators.crosschecker.constants import AGENT
from app.aggregators.crosschecker.rule_recap import recap
from app.contracts import AgentReport, AgentStatus, Case, Finding

STUB_VERSION = "1.0.0-stub"


def review(case: Case, rule_findings: list[Finding]) -> AgentReport:
    """The rule findings unchanged, with the template recap. `case` is unused but kept so the
    stub mirrors the real `review`."""
    del case
    return AgentReport(
        agent=AGENT,
        version=STUB_VERSION,
        status=AgentStatus.OK,
        input_hash="",
        findings=list(rule_findings),
        summary=recap(rule_findings),
    )
