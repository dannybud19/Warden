"""Request models. These are API-only, so they live here and not in contracts."""

from typing import Literal, Self

from pydantic import BaseModel, model_validator

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
        return self
