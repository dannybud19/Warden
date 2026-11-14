"""Request models. These are API-only, so they live here and not in contracts."""

from pydantic import BaseModel

from app.contracts import Landlord, Listing, StudentContext


class OpenCaseRequest(BaseModel):
    student: StudentContext = StudentContext()
    listing: Listing | None = None
    landlord: Landlord | None = None


class ReplyRequest(BaseModel):
    text: str
    evidence_ids: list[str] = []
