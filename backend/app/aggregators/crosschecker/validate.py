"""Turn the LLM's disagreements into findings only when both quotes check out; clean the recap."""

import logging

from app.aggregators.crosschecker.constants import AGENT, ID_PREFIX, NOT_RUN_ID, RULE_IDS
from app.aggregators.crosschecker.models import Inconsistency, ReviewOutput
from app.aggregators.crosschecker.sources import Source
from app.contracts import Category, CheckId, Finding, Severity


def to_findings(
    output: ReviewOutput,
    sources: list[Source],
    rule_findings: list[Finding],
    *,
    log: logging.Logger | None = None,
) -> tuple[list[Finding], list[Inconsistency]]:
    """The consistency findings for the inconsistencies that pass V1 to V7, and those kept."""
    raise NotImplementedError


def clean_recap(recap: str, kept: list[Inconsistency], rule_findings: list[Finding]) -> str | None:
    """The LLM recap made fit to show, the template if it breaks a rule, None if nothing kept."""
    raise NotImplementedError


def not_run_finding(reason: str) -> Finding:
    """The info finding that says the LLM pass failed this time (plan Appendix C)."""
    return Finding(
        id=NOT_RUN_ID,
        agent=AGENT,
        check_id=CheckId.CONTRACT_CONSISTENCY,
        title="Cross-check could not run this time",
        detail=(
            f"The comparison between agents' reports failed ({reason}). "
            "Rule-based checks still ran."
        ),
        category=Category.CONSISTENCY,
        severity=Severity.INFO,
        confidence=0.0,
        evidence=[],
        supports="suspicious",
        hard_flag=False,
    )


def is_llm_finding(finding: Finding) -> bool:
    """True for a consistency finding the LLM pass made (not a rule finding, not `not-run`)."""
    return (
        finding.id.startswith(ID_PREFIX) and finding.id not in RULE_IDS and finding.id != NOT_RUN_ID
    )
