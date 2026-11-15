"""Structured output the orchestrator asks the LLM for. Internal: never part of `contracts/`."""

from typing import Literal

from pydantic import BaseModel

Outcome = Literal["clears", "flags", "neutral"]

FieldName = Literal[
    "landlord.company_number",
    "landlord.name",
    "listing.rent_pcm",
    "listing.deposit",
    "student.move_in_date",
]


class LLMActionUpdate(BaseModel):
    """The LLM's reading of how the reply answers one open action."""

    action_id: str
    outcome: Outcome
    quote: str  # exact span of the student's text; checked in code, dropped if not found
    evidence_ids: list[str] = []  # files attached to the reply that this answer relies on


class LLMFieldUpdate(BaseModel):
    """A case field the student stated in the reply (P2). Validated and normalised in code."""

    field: FieldName
    value: str
    quote: str
    correction: bool = False  # the student explicitly corrects a value we already hold


class LLMParseOutput(BaseModel):
    """The whole parse reply.

    `updates` is required on purpose: a reply without it (for example the `{}` that `FakeLLM`
    returns when no API key is set) is malformed and must take the keyword fallback, not be read
    as "the reply answered nothing".
    """

    updates: list[LLMActionUpdate]
    question: str | None = None  # P2: a question the student asked us
    fields: list[LLMFieldUpdate] = []  # P2
