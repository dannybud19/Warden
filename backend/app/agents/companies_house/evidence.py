"""Finding and evidence builders that enforce the App. C convention in one place."""

from collections.abc import Iterable, Sequence

from app.agents.companies_house.constants import (
    AGENT_NAME,
    CH_PUBLIC_URL,
    CONF,
    EV_REGISTER,
    MAX_QUOTE_CHARS,
)
from app.contracts import (
    Case,
    Category,
    CheckId,
    EvidenceRef,
    Finding,
    Severity,
)


def register_url(number: str) -> str:
    """Public Companies House page for a company, cited in `Source:` lines."""
    return CH_PUBLIC_URL.format(number=number)


def ch_ref(field: str, value: object) -> EvidenceRef:
    """Evidence for a register fact: quote is '<field>: <value as returned>'."""
    return EvidenceRef(evidence_id=EV_REGISTER, quote=f"{field}: {value}")


def source_lines(urls: Iterable[str]) -> str:
    """One 'Source: <url>' line per distinct URL, in order."""
    seen: list[str] = []
    for url in urls:
        if url and url not in seen:
            seen.append(url)
    return "\n".join(f"Source: {u}" for u in seen)


def clip_around(text: str, needle: str, limit: int = MAX_QUOTE_CHARS) -> str | None:
    """A verbatim substring of `text` (<= limit chars) containing `needle`, or None if absent."""
    index = text.lower().find(needle.lower())
    if index == -1:
        return None
    start = max(0, index - (limit - len(needle)) // 2)
    end = min(len(text), start + limit)
    return text[start:end].strip() or None


def student_refs(case: Case, needles: Iterable[str]) -> list[EvidenceRef]:
    """One EvidenceRef quoting the student's own message that names any of `needles`, if any."""
    wanted = [n for n in needles if n and n.strip()]
    for message in case.messages:
        for needle in wanted:
            quote = clip_around(message.text, needle)
            if quote:
                return [EvidenceRef(evidence_id=message.evidence_id, quote=quote)]
    return []


def make_finding(
    slug: str,
    *,
    title: str,
    detail: str,
    severity: Severity,
    confidence: float,
    evidence: Sequence[EvidenceRef],
    sources: Iterable[str] = (),
    supports: str = "suspicious",
    hard_flag: bool = False,
    category: Category = Category.IDENTITY,
    check_id: CheckId = CheckId.LANDLORD_IDENTITY,
) -> Finding:
    """Build a Finding with id 'companies_house:<slug>' and `Source:` lines appended to detail.

    Raises ValueError when no evidence has a non-empty quote (golden rule 6): callers inside a
    module let that surface as a failed module rather than emit an unquoted finding.
    """
    refs = [e for e in evidence if e.quote and e.quote.strip()]
    if not refs:
        raise ValueError(f"finding {slug!r} has no quoted evidence")
    src = source_lines(sources)
    return Finding(
        id=f"{AGENT_NAME}:{slug}",
        agent=AGENT_NAME,
        check_id=check_id,
        title=title,
        detail=f"{detail}\n{src}" if src else detail,
        category=category,
        severity=severity,
        confidence=confidence,
        evidence=refs,
        supports="cleared" if supports == "cleared" else "suspicious",
        hard_flag=hard_flag,
    )


def not_run_finding(module: str, failed: Sequence[str]) -> Finding:
    """Info finding so a failure is never mistaken for 'nothing found' (App. D)."""
    listed = "; ".join(failed)
    return make_finding(
        f"not-run-{module}",
        title="Some background checks could not run",
        detail=f"Could not run: {listed}. Results above are incomplete.",
        severity=Severity.INFO,
        confidence=CONF["not-run"],
        evidence=[EvidenceRef(evidence_id=EV_REGISTER, quote=f"could not run: {listed}")],
    )
