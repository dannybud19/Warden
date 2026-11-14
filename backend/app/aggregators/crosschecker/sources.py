"""The numbered sources the LLM may quote, and the input hash that decides reruns."""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any, Literal

from pydantic import BaseModel

from app.aggregators.crosschecker.constants import AGENT
from app.contracts import (
    AgentReport,
    AgentStatus,
    Case,
    Evidence,
    EvidenceKind,
    EvidenceRef,
    Finding,
)
from app.core.agent import hash_slice

SourceKind = Literal["finding", "quote", "fact", "evidence", "message", "student"]

SOURCE_BUDGET = 24_000  # total characters of source text sent to the LLM
EVIDENCE_EXCERPT = 4_000  # characters kept from each evidence's extracted text
MIN_TRIMMED = 500  # budget trimming never cuts an evidence or message source below this
UPLOAD = "upload"  # `agent` of evidence and message sources
STUDENT = "student"  # `agent` of listing and landlord sources
EVIDENCE_KINDS = frozenset(
    {EvidenceKind.CONTRACT, EvidenceKind.DOCUMENT, EvidenceKind.EMAIL, EvidenceKind.CHAT_EXPORT}
)
TRIMMABLE_KINDS: frozenset[SourceKind] = frozenset({"evidence", "message"})
NOT_RUN_MARK = ":not-run"  # in the id of an info finding that says part of an agent failed
SENTENCE_ENDS = (".", "!", "?")


@dataclass(frozen=True)
class Source:
    id: str  # "S1", "S2", ...
    agent: str  # report's agent, or UPLOAD / STUDENT
    evidence_id: str  # where a quote from this source points
    kind: SourceKind
    text: str  # what the LLM sees and what its quotes are checked against


def input_reports(case: Case) -> dict[str, AgentReport]:
    """The OK reports of the other agents (never the Cross-checker's own), sorted by agent."""
    return {
        name: report
        for name, report in sorted(case.reports.items())
        if name != AGENT and report.status == AgentStatus.OK
    }


def input_hash(case: Case, reports: dict[str, AgentReport]) -> str:
    """Hash of everything the LLM pass reads; unchanged means the previous result still holds.

    Beyond the plan's report and student slice, it also covers the evidence and message ids:
    the LLM reads those directly, so an upload that no agent reads must still trigger a pass.
    """
    return hash_slice(
        {
            "reports": [
                {
                    "agent": name,
                    "input_hash": report.input_hash,
                    "findings": [finding.id for finding in report.findings],
                    "facts": [[fact.key.value, fact.value] for fact in report.facts],
                }
                for name, report in reports.items()
            ],
            "listing": _dump(case.listing),
            "landlord": _dump(case.landlord),
            "evidence": [evidence.id for evidence in case.evidence if _readable(evidence)],
            "messages": [message.id for message in case.messages],
        }
    )


def collect(case: Case, reports: dict[str, AgentReport]) -> list[Source]:
    """Every source, numbered S1.. in a stable order, before the budget is applied."""
    unnumbered = [
        *_report_sources(reports),
        *_evidence_sources(case),
        *_message_sources(case),
        *_student_sources(case),
    ]
    ordered = sorted(unnumbered, key=lambda source: source.agent)  # stable: keeps build order
    return [replace(source, id=f"S{n}") for n, source in enumerate(ordered, start=1)]


def fit_budget(sources: list[Source], budget: int = SOURCE_BUDGET) -> tuple[list[Source], int]:
    """`sources` within `budget` characters, and how many sources were trimmed.

    Only evidence and message sources are cut, longest first, to one shared cap that never goes
    below `MIN_TRIMMED`, so findings, quotes, facts and what the student typed stay whole.
    """
    if sum(len(source.text) for source in sources) <= budget:
        return sources, 0
    lengths = [len(s.text) for s in sources if s.kind in TRIMMABLE_KINDS]
    fixed = sum(len(s.text) for s in sources if s.kind not in TRIMMABLE_KINDS)
    cap = _trim_cap(lengths, budget - fixed)
    fitted = [
        replace(s, text=s.text[:cap]) if s.kind in TRIMMABLE_KINDS and len(s.text) > cap else s
        for s in sources
    ]
    trimmed = sum(1 for before, after in zip(sources, fitted, strict=True) if before is not after)
    return fitted, trimmed


def build_sources(case: Case) -> list[Source]:
    """The numbered sources for `case`, within the budget."""
    return fit_budget(collect(case, input_reports(case)))[0]


def _report_sources(reports: dict[str, AgentReport]) -> Iterator[Source]:
    """Each report's findings (each followed by its quotes), then its facts."""
    for name, report in reports.items():
        for finding in report.findings:
            if NOT_RUN_MARK in finding.id:
                continue
            first_id = finding.evidence[0].evidence_id if finding.evidence else ""
            yield _source(name, first_id, "finding", _finding_text(finding))
            for ref in _quoted_refs(finding):
                yield _source(name, ref.evidence_id, "quote", ref.quote or "")
        for fact in report.facts:
            yield _source(name, fact.source, "fact", f"{fact.key.value} = {fact.value}")


def _evidence_sources(case: Case) -> Iterator[Source]:
    """An excerpt of each readable upload."""
    for evidence in case.evidence:
        if _readable(evidence):
            text = (evidence.extracted_text or "")[:EVIDENCE_EXCERPT]
            yield _source(UPLOAD, evidence.id, "evidence", text)


def _message_sources(case: Case) -> Iterator[Source]:
    """Each parsed message, with its sender."""
    for message in case.messages:
        yield _source(UPLOAD, message.evidence_id, "message", f"[{message.sender}] {message.text}")


def _student_sources(case: Case) -> Iterator[Source]:
    """One source per field the student filled in on the listing, then on the landlord."""
    for evidence_id, model in (("listing", case.listing), ("landlord", case.landlord)):
        if model is None:
            continue
        for field, value in model.model_dump().items():
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            yield _source(STUDENT, evidence_id, "student", f"{field}: {value}")


def _source(agent: str, evidence_id: str, kind: SourceKind, text: str) -> Source:
    """A source not yet numbered (`collect` sets the id once the order is final)."""
    return Source(id="", agent=agent, evidence_id=evidence_id, kind=kind, text=text)


def _finding_text(finding: Finding) -> str:
    """'<title>. <detail>' with each non-empty quote on its own line."""
    separator = " " if finding.title.endswith(SENTENCE_ENDS) else ". "
    head = f"{finding.title}{separator}{finding.detail}".rstrip()
    quotes = [f'quote: "{ref.quote}"' for ref in _quoted_refs(finding)]
    return "\n".join([head, *quotes])


def _quoted_refs(finding: Finding) -> list[EvidenceRef]:
    """The finding's evidence refs that carry a non-empty quote."""
    return [ref for ref in finding.evidence if ref.quote and ref.quote.strip()]


def _readable(evidence: Evidence) -> bool:
    """An upload whose extracted text the LLM reads directly."""
    return evidence.kind in EVIDENCE_KINDS and bool((evidence.extracted_text or "").strip())


def _dump(model: BaseModel | None) -> dict[str, Any] | None:
    """A JSON-safe dump for hashing."""
    return model.model_dump(mode="json") if model is not None else None


def _trim_cap(lengths: list[int], room: int) -> int:
    """The largest per-source cap (>= MIN_TRIMMED) whose capped lengths fit in `room`.

    Water-filling: cutting every source to one shared cap trims the longest first. When even
    `MIN_TRIMMED` does not fit, it is used anyway (the floor wins over the budget).
    """
    low, high = MIN_TRIMMED, max(lengths, default=MIN_TRIMMED)
    while low < high:
        mid = (low + high + 1) // 2
        if sum(min(length, mid) for length in lengths) <= room:
            low = mid
        else:
            high = mid - 1
    return low
