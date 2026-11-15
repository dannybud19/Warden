"""Shapes used by the listing reader. Local to this package."""

from typing import Literal

from pydantic import BaseModel

FIELDS = (
    "address",
    "postcode",
    "rent_pcm",
    "deposit",
    "agency_name",
    "company_number",
    "landlord_name",
    "description",
)


class ListingDetails(BaseModel):
    """What one listing page says. Every filled field has the page text it came from in `quotes`."""

    url: str
    status: Literal["ok", "skipped", "unsafe_url", "unreachable", "blocked", "empty"] = "ok"
    via: Literal["linkup", "direct", ""] = ""
    platform: str | None = None
    address: str | None = None
    postcode: str | None = None  # full ("W12 8QT") or the district only ("W12")
    rent_pcm: int | None = None
    deposit: int | None = None
    agency_name: str | None = None
    company_number: str | None = None
    landlord_name: str | None = None
    description: str | None = None
    quotes: dict[str, str] = {}

    def found(self) -> list[str]:
        """Names of the fields the page gave us."""
        return [name for name in FIELDS if getattr(self, name) is not None]


class Quoted(BaseModel):
    value: str
    quote: str = ""  # copied character for character from the page


class LLMListing(BaseModel):
    """The model's reading of the page. A value is kept only if its quote is in the page."""

    address: Quoted | None = None
    rent: Quoted | None = None
    rent_period: Literal["month", "week"] = "month"
    deposit: Quoted | None = None
    agency_name: Quoted | None = None
    company_number: Quoted | None = None
    landlord_name: Quoted | None = None
    summary: str = ""
