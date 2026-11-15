"""Which disagreements a Cross-checker report holds, and whether two of them are the same one.

The LLM names a finding after its topic, so a rerun can describe the same disagreement under a new
id. Two findings are therefore the same disagreement when their ids match **or** they quote the
same two places: for every quote of one there is a quote of the other on the same evidence where
one contains the other (after normalising), and the other way round.
"""

from app.aggregators.crosschecker.constants import NOT_RUN_ID
from app.aggregators.crosschecker.sources import Source, quotable
from app.aggregators.crosschecker.validate import normalise
from app.contracts import AgentReport, Finding


def of_report(report: AgentReport) -> list[Finding]:
    """The report's disagreements: its suspicious findings, not the not-run notice."""
    return [f for f in report.findings if f.supports == "suspicious" and f.id != NOT_RUN_ID]


def same(a: Finding, b: Finding) -> bool:
    """`a` and `b` are the same disagreement (same id, or the same two quoted places)."""
    if a.id == b.id:
        return True
    quotes_a, quotes_b = _quotes(a), _quotes(b)
    return bool(quotes_a) and _covered(quotes_a, quotes_b) and _covered(quotes_b, quotes_a)


def unseen(findings: list[Finding], seen: list[Finding]) -> list[Finding]:
    """The `findings` that are none of the `seen` disagreements."""
    return [f for f in findings if not any(same(f, s) for s in seen)]


def still_quoted(finding: Finding, sources: list[Source]) -> bool:
    """Every quote of `finding` is still in the evidence it cites (a source with that evidence
    id), so the disagreement can still be checked against what the student has."""
    return all(
        any(
            source.evidence_id == ref.evidence_id and needle in normalise(quotable(source))
            for source in sources
        )
        for ref in finding.evidence
        if ref.quote and (needle := normalise(ref.quote))
    )


def _quotes(finding: Finding) -> list[tuple[str, str]]:
    """(evidence id, normalised quote) for each quote of the finding."""
    return [
        (ref.evidence_id, normalise(ref.quote))
        for ref in finding.evidence
        if ref.quote and ref.quote.strip()
    ]


def _covered(quotes: list[tuple[str, str]], others: list[tuple[str, str]]) -> bool:
    """Each quote has a counterpart in `others` on the same evidence, one containing the other."""
    return all(
        any(ev == other_ev and (text in other or other in text) for other_ev, other in others)
        for ev, text in quotes
    )
