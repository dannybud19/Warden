"""The numbered sources the LLM may quote, and the input hash that decides reruns."""

from dataclasses import dataclass
from typing import Literal

from app.aggregators.crosschecker.constants import AGENT
from app.contracts import AgentReport, AgentStatus, Case, EvidenceKind

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
    """Hash of everything the LLM pass reads; unchanged means the previous result still holds."""
    raise NotImplementedError


def collect(case: Case, reports: dict[str, AgentReport]) -> list[Source]:
    """Every source, numbered S1.. in a stable order, before the budget is applied."""
    raise NotImplementedError


def fit_budget(sources: list[Source], budget: int = SOURCE_BUDGET) -> tuple[list[Source], int]:
    """`sources` within `budget` characters, and how many sources were trimmed."""
    raise NotImplementedError


def build_sources(case: Case) -> list[Source]:
    """The numbered sources for `case`, within the budget."""
    return fit_budget(collect(case, input_reports(case)))[0]
