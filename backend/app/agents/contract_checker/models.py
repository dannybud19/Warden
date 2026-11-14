"""Private, versioned models for contract review; shared contracts stay unchanged."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuleId(StrEnum):
    DEPOSIT = "deposit_cap"
    HOLDING = "holding_deposit_cap"
    FEES = "prohibited_fee"
    ADVANCE = "advance_rent"
    STRUCTURE = "tenancy_structure"
    NOTICE = "tenant_notice"
    CONFLICT = "internal_conflict"
    SCHEDULE = "missing_schedule"
    OBLIGATION = "unusual_obligation"


class ReviewContext(StrictModel):
    """Explicit facts supplied by the caller, not inferred from reassuring prose."""

    assessment_date: date
    jurisdiction: Literal["england", "wales", "scotland", "northern_ireland", "unknown"] = "unknown"
    tenancy_type: Literal["ordinary_private", "lodger", "student_halls", "social", "unknown"] = (
        "unknown"
    )
    agreement_date: date | None = None
    tenancy_start_date: date | None = None
    signed_by_both: bool | None = None
    rent_basis: Literal["whole_tenancy", "per_person", "unknown"] = "unknown"
    answers: list[str] = Field(default_factory=list, max_length=20)


class Segment(StrictModel):
    id: str
    text: str
    page: int | None = None
    clause_id: str


class Document(StrictModel):
    id: str
    filename: str
    sha256: str
    segments: list[Segment]
    warnings: list[str] = Field(default_factory=list)


class Quote(StrictModel):
    segment_id: str
    quote: str = Field(min_length=1, max_length=200)


class Citation(Quote):
    document_id: str
    clause_id: str
    page: int | None = None


class MoneyTerm(StrictModel):
    kind: Literal["rent", "deposit", "holding_deposit", "advance_rent"]
    amount: Decimal = Field(ge=0, allow_inf_nan=False)
    frequency: Literal["month", "week", "year", "one_off", "unknown"] = "one_off"
    evidence: Quote


class ExtractedFact(StrictModel):
    kind: Literal["property_address", "landlord_name", "move_in_date"]
    value: str = Field(min_length=1, max_length=250)
    evidence: Quote


class Candidate(StrictModel):
    rule_id: RuleId
    title: str = Field(min_length=1, max_length=160)
    explanation: str = Field(min_length=1, max_length=1200)
    evidence: list[Quote] = Field(min_length=1, max_length=5)
    uncertainty: list[str] = Field(default_factory=list, max_length=5)


class Extraction(StrictModel):
    money: list[MoneyTerm] = Field(default_factory=list, max_length=50)
    facts: list[ExtractedFact] = Field(default_factory=list, max_length=20)
    candidates: list[Candidate] = Field(default_factory=list, max_length=30)
    reviewed_rules: list[RuleId] = Field(default_factory=list)


class Question(StrictModel):
    id: str
    rule_id: RuleId
    text: str
    why: str
    resolves_when: str


class LegalSource(StrictModel):
    title: str
    url: str
    verified_on: date


class Issue(StrictModel):
    id: str
    rule_id: RuleId
    status: Literal["confirmed", "conditional", "cleared", "dismissed"]
    supports: Literal["suspicious", "cleared"] = "suspicious"
    title: str
    explanation: str
    evidence: list[Citation] = Field(min_length=1)
    legal_sources: list[LegalSource] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    importance: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    calculation: str | None = None
    question: Question | None = None
    origin: Literal["rule", "llm"]
    review_reason: str | None = None
    counter_evidence: list[Citation] = Field(default_factory=list)


class Challenge(StrictModel):
    issue_id: str
    decision: Literal["uphold", "conditional", "dismiss"]
    reason: str = Field(min_length=1, max_length=1200)
    counter_evidence: list[Quote] = Field(default_factory=list, max_length=5)


class ChallengeResponse(StrictModel):
    decisions: list[Challenge] = Field(default_factory=list, max_length=60)


class ContractReview(StrictModel):
    schema_version: str = "1.0"
    rulebook_version: str = "england-2026-11-14"
    status: Literal["complete", "partial", "needs_input", "unsupported"]
    context: ReviewContext
    document_id: str
    document_sha256: str
    issues: list[Issue] = Field(default_factory=list)
    money: list[MoneyTerm] = Field(default_factory=list)
    facts: list[ExtractedFact] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reviewed_rules: list[RuleId] = Field(default_factory=list)
    extraction_completed: bool = False
    challenge_completed: bool = False
    duration_ms: int = 0
