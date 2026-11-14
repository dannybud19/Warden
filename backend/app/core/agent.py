"""BaseAgent, AgentContext and the helpers that decide what an agent reads."""

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar

import httpx

from app.contracts import (
    AgentReport,
    AgentStatus,
    Case,
    Evidence,
    EvidenceKind,
    Fact,
    Finding,
)
from app.core.llm import LLMClient
from app.core.search import WebSearchClient
from app.core.settings import Settings


class Need(StrEnum):
    MESSAGES = "messages"
    CONTRACT = "contract"
    LANDLORD = "landlord"
    LISTING = "listing"
    VIDEO = "video"


@dataclass(frozen=True)
class AgentContext:
    llm: LLMClient
    search: WebSearchClient
    http: httpx.AsyncClient
    settings: Settings
    log: logging.Logger


def _evidence_of(case: Case, kind: EvidenceKind) -> list[Evidence]:
    return [e for e in case.evidence if e.kind == kind and e.extracted_text]


def has_need(case: Case, need: Need) -> bool:
    """True when the Case holds what this need stands for."""
    match need:
        case Need.MESSAGES:
            return bool(case.messages)
        case Need.CONTRACT:
            return bool(_evidence_of(case, EvidenceKind.CONTRACT))
        case Need.LANDLORD:
            ll = case.landlord
            return ll is not None and bool(ll.name or ll.company_name or ll.company_number)
        case Need.LISTING:
            return case.listing is not None
        case Need.VIDEO:
            return any(e.kind == EvidenceKind.VIDEO for e in case.evidence)


def slice_for(case: Case, needs: frozenset[Need]) -> dict[str, Any]:
    """Everything an agent with these needs may read. Answers are always included,
    so every agent reruns after the student answers a question."""
    out: dict[str, Any] = {
        "answers": [a.model_dump(mode="json") for a in case.actions if a.answer],
        "student": case.student.model_dump(mode="json"),
    }
    if Need.MESSAGES in needs:
        out["messages"] = [m.model_dump(mode="json") for m in case.messages]
    if Need.CONTRACT in needs:
        out["contract"] = [
            e.model_dump(mode="json") for e in _evidence_of(case, EvidenceKind.CONTRACT)
        ]
    if Need.LANDLORD in needs:
        out["landlord"] = case.landlord.model_dump(mode="json") if case.landlord else None
    if Need.LISTING in needs:
        out["listing"] = case.listing.model_dump(mode="json") if case.listing else None
    if Need.VIDEO in needs:
        out["video"] = [e.id for e in case.evidence if e.kind == EvidenceKind.VIDEO]
    return out


def hash_slice(data: dict[str, Any]) -> str:
    """Stable short hash of an input slice."""
    raw = json.dumps(data, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


class BaseAgent(ABC):
    name: ClassVar[str]
    version: ClassVar[str] = "0.1.0"
    requires: ClassVar[frozenset[Need]] = frozenset()
    timeout_s: ClassVar[float] = 45.0

    def input_slice(self, case: Case) -> dict[str, Any]:
        """The parts of the Case this agent reads. Hashed to skip unchanged reruns."""
        return slice_for(case, self.requires)

    def report(
        self,
        case: Case,
        *,
        status: AgentStatus = AgentStatus.OK,
        findings: Sequence[Finding] = (),
        facts: Sequence[Fact] = (),
        questions: Sequence[str] = (),
        error: str | None = None,
    ) -> AgentReport:
        """Build a report with agent name, version and input hash filled in."""
        return AgentReport(
            agent=self.name,
            version=self.version,
            status=status,
            input_hash=hash_slice(self.input_slice(case)),
            findings=list(findings),
            facts=list(facts),
            questions=list(questions),
            error=error,
        )

    @abstractmethod
    async def run(self, case: Case, ctx: AgentContext) -> AgentReport: ...
