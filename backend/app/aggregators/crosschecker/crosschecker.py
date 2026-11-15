"""Cross-checker (WS J): reads every agent's report side by side and flags where they disagree.

The orchestrator computes the rule findings (`orchestrator.crosscheck.compare`) and passes them in,
because aggregators may not import the orchestrator. They are returned first and unchanged; the
LLM's consistency findings follow, and the recap goes in `summary` for the orchestrator to relay.
"""

import asyncio
import time

from app.aggregators.crosschecker import disagreements, llm_pass, sources, stub, validate
from app.aggregators.crosschecker.constants import AGENT
from app.aggregators.crosschecker.rule_recap import recap, rule_topics
from app.aggregators.crosschecker.validate import MAX_KEPT
from app.contracts import AgentReport, AgentStatus, Case, Finding
from app.core.agent import AgentContext

__all__ = ["LLM_TIMEOUT_S", "MIN_INPUTS", "NAME", "VERSION", "recap", "review"]

NAME = AGENT
VERSION = "1.0.0"
MIN_INPUTS = 2  # fewer OK reports than this leaves nothing to compare
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
    srcs, trimmed = sources.fit_budget(sources.collect(case, inputs))
    # Our own skip key: the material we compare, not the agents' input hashes (those change with
    # every action answer, and the LLM would word the same disagreements differently each time).
    digest = sources.digest(srcs)

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

    if len(inputs) < MIN_INPUTS:
        summary = previous.summary if previous and carried else recap(rules)
        return report(rules + carried, summary, digest)

    if previous and previous.input_hash == digest and previous.version == VERSION:
        return report(rules + carried, previous.summary, digest)

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

    found, kept = validate.to_findings(output, srcs, rules, log=ctx.log)
    # A verified disagreement does not vanish because this run worded things differently: it stays
    # while its quotes are still in the evidence, unless this run found the same one again.
    kept_over = [
        f
        for f in carried
        if disagreements.still_quoted(f, srcs) and not any(disagreements.same(f, n) for n in found)
    ][: max(MAX_KEPT - len(found), 0)]
    if kept_over:
        summary = _summary_with(kept_over, found, rules, previous)
    else:
        summary = validate.clean_recap(output.recap, kept, rules) if kept else recap(rules)
    return report(rules + found + kept_over, summary, digest)


def _summary_with(
    kept_over: list[Finding],
    found: list[Finding],
    rules: list[Finding],
    previous: AgentReport | None,
) -> str:
    """The recap when earlier disagreements are carried over: the previous one if this run found
    nothing new, else the fixed template naming every topic."""
    if not found and previous and previous.summary:
        return previous.summary
    topics = [
        *rule_topics([f for f in rules if f.supports == "suspicious"]),
        *(_topic(f) for f in [*kept_over, *found]),
    ]
    return validate.template_recap(topics)


def _topic(finding: Finding) -> str:
    """The topic a consistency finding's title starts with ("Utilities: A and B disagree")."""
    return finding.title.partition(":")[0]


def _verified_before(previous: AgentReport | None) -> list[Finding]:
    """The LLM findings of the previous run, when it was made by this version."""
    if previous is None or previous.version != VERSION:
        return []
    return [f for f in previous.findings if validate.is_llm_finding(f)]
