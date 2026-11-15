"""Request models. These are API-only, so they live here and not in contracts."""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.contracts import Landlord, Listing, StudentContext


class OpenCaseRequest(BaseModel):
    student: StudentContext = StudentContext()
    listing: Listing | None = None
    landlord: Landlord | None = None


class ReplyRequest(BaseModel):
    text: str
    evidence_ids: list[str] = []
    action_id: str | None = None
    status: Literal["done", "skipped", "impossible"] | None = None

    @model_validator(mode="after")
    def _status_needs_action(self) -> Self:
        """A status applies to one action, so it needs `action_id` (422 otherwise)."""
        if self.status is not None and self.action_id is None:
            raise ValueError("status needs action_id")
        if not self.text.strip() and self.status is None:
            # A blank chat message says nothing; only a skip from a step's card may have no text.
            raise ValueError("text is empty")
        return self


class DebriefLine(BaseModel):
    """One spoken turn of a voice call. `at` defaults to the time the debrief arrives."""

    role: Literal["student", "orchestrator"]
    text: str
    at: datetime | None = None


class DebriefAnswer(BaseModel):
    """An answer the voice agent recorded for one open action during the call."""

    action_id: str
    answer: str
    status: Literal["done", "skipped", "impossible"] = "done"


class DebriefRequest(BaseModel):
    """The whole call, sent once when it ends (`POST /cases/{id}/debrief`)."""

    source: Literal["call"] = "call"
    started_at: datetime | None = None
    lines: list[DebriefLine] = Field(min_length=1)
    answers: list[DebriefAnswer] = []

    @model_validator(mode="after")
    def _has_words(self) -> Self:
        """A call with no spoken words has nothing to debrief (422)."""
        if not any(line.text.strip() for line in self.lines):
            raise ValueError("lines are empty")
        return self


class ListingPreviewRequest(BaseModel):
    url: str


class ListingPreview(BaseModel):
    """What a listing page states, to prefill the add-home form before a case exists.

    `status` is `ok`, `skipped` (reader in stub mode), `unsafe_url`, `unreachable`, `blocked` or
    `empty`; `message` is one plain line for the student; `quotes` holds the page text each
    filled field came from.
    """

    status: str
    message: str | None = None
    platform: str | None = None
    address: str | None = None
    postcode: str | None = None
    rent_pcm: int | None = None
    deposit: int | None = None
    agency_name: str | None = None
    company_number: str | None = None
    landlord_name: str | None = None
    description: str | None = None
    quotes: dict[str, str] = {}
