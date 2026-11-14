"""Cross-checker stub: passes the rule findings through and writes a template recap.

The orchestrator computes the rule findings (`orchestrator.crosscheck.compare`) and passes them in,
because aggregators may not import the orchestrator. The LLM version (WS J) replaces `review` and
keeps its signature.
"""

from app.contracts import AgentReport, AgentStatus, Case, Finding, Severity
from app.core.agent import AgentContext

NAME = "crosscheck"
VERSION = "0.1.0"

TITLE_SUFFIX = " differs between sources"
MAX_TOPICS = 6  # keeps the recap short; the rest are counted, not named
URGENT_SEVERITIES = frozenset({Severity.CRITICAL, Severity.HIGH})
WARNING = " Check these before you pay."


async def review(case: Case, rule_findings: list[Finding], ctx: AgentContext) -> AgentReport:
    """The report stored as `case.reports["crosscheck"]`, with the recap in `summary`."""
    return AgentReport(
        agent=NAME,
        version=VERSION,
        status=AgentStatus.OK,
        input_hash="",
        findings=list(rule_findings),
        summary=recap(rule_findings),
    )


def recap(findings: list[Finding]) -> str | None:
    """One or two plain sentences naming what the sources disagree on; None when nothing does."""
    disagreements = [f for f in findings if f.supports == "suspicious"]
    topics = _topics(disagreements)
    if not topics:
        return None
    sentence = _topic_sentence(topics)
    return sentence + WARNING if any(_is_urgent(f) for f in disagreements) else sentence


def _topic(title: str) -> str:
    """The thing a title is about: "Rent differs between sources" becomes "rent"."""
    return title.removesuffix(TITLE_SUFFIX).strip().lower()


def _topics(findings: list[Finding]) -> list[str]:
    """Unique topics in the order their findings appear."""
    return list(dict.fromkeys(_topic(f.title) for f in findings))


def _topic_sentence(topics: list[str]) -> str:
    """The recap's first sentence; names at most `MAX_TOPICS` topics."""
    if len(topics) == 1:
        return f"Two sources disagree on the {topics[0]}."
    shown = ", ".join(topics[:MAX_TOPICS])
    hidden = len(topics) - MAX_TOPICS
    more = f" and {hidden} more" if hidden > 0 else ""
    return f"Sources disagree on: {shown}{more}."


def _is_urgent(finding: Finding) -> bool:
    """A disagreement serious enough to warn the student before paying."""
    return finding.hard_flag or finding.severity in URGENT_SEVERITIES
