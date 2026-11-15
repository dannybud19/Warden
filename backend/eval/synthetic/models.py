"""Generator-owned specifications; the application's shared schemas remain unchanged."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import CheckId

FAMILIES = (
    "deceptive_short_let",
    "fake_platform_link",
    "unavailable_advert",
    "fake_agency",
    "prepaid_payment",
    "property_for_sale",
    "overpayment",
    "transfer_pressure",
)

Outcome = Literal[
    "pending", "not_verified", "likely_scam", "proceed_with_care", "no_red_flags_remaining"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatTurn(StrictModel):
    sender: Literal["student", "agent"]
    text: str = Field(min_length=1)


class Expectation(StrictModel):
    check_id: CheckId
    topic: str
    stance: Literal["concern", "clarify", "must_not_assert"]
    source: Literal["chat", "contract", "external"]
    quote: str = Field(min_length=1)
    explanation: str


class ExternalRecord(StrictModel):
    key: str
    query_terms: list[str] = Field(min_length=1)
    query_alternatives: list[list[str]] = Field(default_factory=list)
    outcome: Literal["found", "not_found", "unavailable"]
    title: str
    url: str
    snippet: str
    company_status: Literal["active", "dissolved"] | None = None


class FollowUp(StrictModel):
    check_id: CheckId
    topic: str
    text: str = Field(min_length=1)
    expected_change: str
    available_at: datetime = datetime(2026, 11, 16, 12, tzinfo=UTC)


class Scenario(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    family: str
    variant: Literal["concern", "genuine", "unresolved", "compound", "robustness", "paraphrase"]
    truth: Literal["scam", "genuine", "unknown"]
    messages: list[ChatTurn] = Field(min_length=2)
    contract_extra: str = ""
    expectations: list[Expectation] = Field(min_length=1)
    forbidden_assertions: list[str] = Field(default_factory=list)
    allowed_outcomes: list[Outcome] = Field(min_length=1)
    external: list[ExternalRecord] = Field(default_factory=list)
    follow_up: FollowUp | None = None
    commitments: dict[str, str] = Field(default_factory=dict)
    parent_key: str | None = None
    viewing_completed: bool = False


class Rewrite(StrictModel):
    message_index: int = Field(ge=0)
    text: str = Field(min_length=1)


class Paraphrase(StrictModel):
    base_key: str
    rewrites: list[Rewrite] = Field(min_length=1)
    quote_replacements: dict[str, str] = Field(default_factory=dict)


class SourceReference(StrictModel):
    source: str
    quote: str


class ManifestExpectation(StrictModel):
    check_id: CheckId
    topic: str
    stance: Literal["concern", "clarify", "must_not_assert"]
    evidence: list[SourceReference]
    explanation: str


class CaseEntry(StrictModel):
    case_id: str
    group_id: str
    family: str
    variant: str
    parent_case_id: str | None = None
    truth: Literal["scam", "genuine", "unknown"]
    files: dict[str, str]
    sha256: dict[str, str]
    expectations: list[ManifestExpectation]
    forbidden_assertions: list[str]
    allowed_outcomes: list[Outcome]
    commitments: dict[str, str]
    follow_up_trigger: dict[str, str] | None = None
    follow_up_expected_change: str | None = None
    follow_up_available_at: datetime | None = None
    label_review: Literal["pending_agent_owner_review"] = "pending_agent_owner_review"
    reviewers: list[str]
    wording_provenance: str


class Comparison(StrictModel):
    baseline_case_id: str
    variant_case_id: str
    kind: Literal["meaningful_change", "wording_only"]
    expected_behavior: str


class Manifest(StrictModel):
    schema_version: str = "1.0"
    generator_version: str = "1.0.0"
    dataset_scope: Literal["development"] = "development"
    assessment_date: str = "2026-11-14"
    seed: int
    source_sha256: dict[str, str]
    generation_api_cost_usd: str = "0"
    notes: list[str]
    cases: list[CaseEntry]
    comparisons: list[Comparison] = Field(default_factory=list)
