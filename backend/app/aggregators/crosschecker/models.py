"""The LLM's structured output. Frozen: `llm_pass`, `validate` and the tests depend on it."""

from typing import Literal

from pydantic import BaseModel, Field

from app.contracts import CheckId


class Side(BaseModel):
    source_id: str  # "S7"; must exist in the source list
    claim: str  # the side's claim in plain words, <= 120 chars
    quote: str  # verbatim substring of that source's text, 3..200 chars


class Inconsistency(BaseModel):
    topic: str  # short noun phrase, e.g. "utilities", "deposit amount", "who to pay"
    check_id: CheckId  # one of the 8; usually contract_consistency, payment topics payment_safety
    severity: Literal["low", "medium", "high"]
    a: Side
    b: Side
    why_it_matters: str  # <= 160 chars, no verdict words


class ReviewOutput(BaseModel):
    inconsistencies: list[Inconsistency] = Field(default_factory=list, max_length=6)
    recap: str = ""  # <= 80 words; empty when there are no inconsistencies
