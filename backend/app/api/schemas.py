"""Request models. These are API-only, so they live here and not in contracts."""

from typing import Literal

from pydantic import BaseModel

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
