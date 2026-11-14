"""Facts and findings that agents emit."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.contracts.checks import CheckId


class FactKey(StrEnum):
    ADDRESS = "address"
    LANDLORD_NAME = "landlord_name"
    COMPANY_NUMBER = "company_number"
    RENT_PCM = "rent_pcm"
    DEPOSIT = "deposit"
    BANK_ACCOUNT = "bank_account"
    EMAIL_DOMAIN = "email_domain"
    MOVE_IN_DATE = "move_in_date"


class Fact(BaseModel):
    key: FactKey
    value: str
    source: str  # evidence id or "listing"/"landlord"
    agent: str


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Category(StrEnum):
    IDENTITY = "identity"
    PAYMENT = "payment"
    PRESSURE = "pressure"
    DOCUMENT = "document"
    PRICING = "pricing"
    PROPERTY = "property"
    CONSISTENCY = "consistency"


class EvidenceRef(BaseModel):
    evidence_id: str
    quote: str | None = None


class Finding(BaseModel):
    id: str  # "<agent>:<slug>", stable across reruns
    agent: str
    check_id: CheckId
    title: str
    detail: str
    category: Category
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceRef] = []
    supports: Literal["suspicious", "cleared"] = "suspicious"  # evidence FOR genuineness: "cleared"
    hard_flag: bool = False
