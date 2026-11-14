"""What an agent returns, the score, and the final decision."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.contracts.checks import CheckId
from app.contracts.findings import Fact, Finding


class AgentStatus(StrEnum):
    OK = "ok"
    SKIPPED = "skipped"
    NEEDS_INPUT = "needs_input"
    ERROR = "error"


class AgentReport(BaseModel):
    agent: str
    version: str
    status: AgentStatus
    input_hash: str  # hash of the Case parts this agent read
    findings: list[Finding] = []
    facts: list[Fact] = []
    questions: list[str] = []  # uncertainty handed to the consultant
    error: str | None = None
    duration_ms: int = 0


class ScoreResult(BaseModel):
    at: datetime
    score: float  # 0 to 100, starts at 100
    contributions: dict[CheckId, float]  # points each check is holding up


class Verdict(StrEnum):
    LIKELY_SCAM = "likely_scam"
    NOT_VERIFIED = "not_verified"
    PROCEED_WITH_CARE = "proceed_with_care"
    NO_RED_FLAGS = "no_red_flags_remaining"


class Decision(BaseModel):
    verdict: Verdict
    decided_at: datetime
    summary: str
    reasons: list[str]
    finding_ids: list[str]
