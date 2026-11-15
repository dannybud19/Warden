"""Cross-checker (WS J): reads every agent's report side by side and flags where they disagree.

The orchestrator computes the rule findings (`orchestrator.crosscheck.compare`) and passes them in,
because aggregators may not import the orchestrator. They are returned first and unchanged; the
LLM's consistency findings follow, and the recap goes in `summary` for the orchestrator to relay.
"""

import asyncio
import time

from app.aggregators.crosschecker import llm_pass, sources, stub, validate
from app.aggregators.crosschecker.constants import AGENT
from app.aggregators.crosschecker.rule_recap import recap
from app.contracts import AgentReport, AgentStatus, Case, EvidenceKind, Finding
from app.core.agent import AgentContext

__all__ = ["LLM_TIMEOUT_S", "MIN_INPUTS", "NAME", "VERSION", "recap", "review"]

NAME = AGENT
VERSION = "1.1.0"  # 1.1: certain listing-vs-contract address mismatches are hard flags
MIN_INPUTS = 2  # fewer sides than this (`_sides`) leaves nothing to compare
# NOTE: below the orchestrator's 30 s deadline around `review`, so our own fallback (with the
# not-run finding) wins over its generic one.
LLM_TIMEOUT_S = 25.0


async def review(case: Case, rule_findings: list[Finding], ctx: AgentContext) -> AgentReport:
    """The report stored as `case.reports["crosscheck"]`, with the recap in `summary`."""
    started = time.monotonic()
    rules = list(rule_findings)
    if ctx.settings.agent_mode(NAME) == "stub":
        return stub.review(case, rules)

    inputs = sources.input_reports(case)
    previous = case.reports.get(NAME)
    digest = sources.input_hash(case, inputs)

    def report(findings: list[Finding], summary: str | None, input_hash: str) -> AgentReport:
        return AgentReport(
            agent=NAME,
            version=VERSION,
            status=AgentStatus.OK,
            input_hash=input_hash,
            findings=findings,
            summary=summary,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # Disagreements this version already verified. Kept when this run can't check again, so a
    # report or LLM call that fails for now does not make them (and the recap) disappear.
    carried = _verified_before(previous)

    if _sides(case, len(inputs)) < MIN_INPUTS:
        summary = previous.summary if previous and carried else recap(rules)
        return report(rules + carried, summary, digest)

    if previous and previous.input_hash == digest and previous.version == VERSION:
        return report(rules + carried, previous.summary, digest)

    collected = sources.collect(case, inputs)
    srcs, trimmed = sources.fit_budget(collected)
    if trimmed:
        ctx.log.info("cross-checker trimmed %d sources to fit the budget", trimmed)

    try:
        output = await asyncio.wait_for(llm_pass.run(srcs, ctx), LLM_TIMEOUT_S)
    except (TimeoutError, llm_pass.LLMPassError) as exc:
        reason = exc.reason if isinstance(exc, llm_pass.LLMPassError) else "it took too long"
        ctx.log.warning("cross-checker LLM pass failed (%s): keeping earlier results", reason)
        # Keep the previous recap so the orchestrator does not send the same one again.
        summary = previous.summary if previous and previous.summary else recap(rules)
        # Empty input hash, so the next analysis retries.
        return report([*rules, *carried, validate.not_run_finding(reason)], summary, "")

    kinds = {evidence.id: evidence.kind for evidence in case.evidence}
    found, kept = validate.to_findings(output, srcs, rules, evidence_kinds=kinds, log=ctx.log)
    summary = validate.clean_recap(output.recap, kept, rules) if kept else recap(rules)
    return report(rules + found, summary, digest)


def _verified_before(previous: AgentReport | None) -> list[Finding]:
    """The LLM findings of the previous run, when it was made by this version."""
    if previous is None or previous.version != VERSION:
        return []
    return [f for f in previous.findings if validate.is_llm_finding(f)]


def _sides(case: Case, ok_reports: int) -> int:
    """How many independent sides can be compared: each OK report, what the student entered about
    the listing or landlord, and each uploaded listing.

    A listing and a contract alone give one OK report (the contract checker), yet the contract
    must still be compared with the listing: that is how a contract for another home is caught.
    """
    entered = any(
        value not in (None, "")
        for model in (case.listing, case.landlord)
        if model is not None
        for value in model.model_dump().values()
    )
    listings = sum(
        1
        for evidence in case.evidence
        if evidence.kind == EvidenceKind.LISTING and (evidence.extracted_text or "").strip()
    )
    return ok_reports + int(entered) + listings
