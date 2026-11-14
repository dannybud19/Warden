"""The 8 checks the orchestrator tracks, and the actions that move them."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class CheckId(StrEnum):
    LANDLORD_IDENTITY = "landlord_identity"
    PAYMENT_SAFETY = "payment_safety"
    RIGHT_TO_LET = "right_to_let"
    IN_PERSON_VIEWING = "in_person_viewing"
    CONTRACT_CONSISTENCY = "contract_consistency"
    DEPOSIT_PROTECTION = "deposit_protection"
    NO_PRESSURE = "no_pressure"
    FAIR_PRICE = "fair_price"


class CheckState(StrEnum):
    UNVERIFIED = "unverified"
    SUSPICIOUS = "suspicious"
    CLEARED = "cleared"


class Check(BaseModel):
    id: CheckId
    state: CheckState = CheckState.UNVERIFIED
    clear_confidence: float = 0.0  # used when CLEARED
    finding_ids: list[str] = []
    reason: str | None = None  # one line for the UI


class ActionKind(StrEnum):
    QUESTION = "question"
    ACTION = "action"


class ActionStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    SKIPPED = "skipped"
    IMPOSSIBLE = "impossible"


class Action(BaseModel):
    id: str
    check_id: CheckId
    kind: ActionKind
    text: str
    status: ActionStatus = ActionStatus.OPEN
    answer: str | None = None
    answer_evidence_ids: list[str] = []
    outcome: Literal["clears", "flags", "neutral"] | None = None  # set by conversation.parse
    asked_at: datetime | None = None
