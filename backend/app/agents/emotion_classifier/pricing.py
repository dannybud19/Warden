"""Rent against an approximate area figure. Pure functions; the table is `area_rents.yaml`."""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from app.contracts import Case, Category, CheckId, EvidenceRef, Finding, Severity

AGENT = "emotion_classifier"
RENTS_PATH = Path(__file__).parent / "area_rents.yaml"
FAR_BELOW = -0.25  # this far under the area figure is a warning sign
IN_LINE = 0.15  # within this band either way counts as in line

Kind = Literal["room", "one_bed"]

_I = re.IGNORECASE
_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*\d[A-Z]{2}\b", _I)
_RENT = re.compile(
    r"£\s?(\d[\d,]*(?:\.\d{1,2})?)\s*(?:pcm|p\.c\.m\.?|per (?:calendar )?month|a month|monthly)",
    _I,
)
_ROOM = re.compile(r"\b(?:room|flat ?share|house ?share|en-?suite|flatmates?|housemates?)\b", _I)
_WHOLE_FLAT = re.compile(
    r"\b(?:studio|(?:one|1)[- ]bed(?:room)?|self[- ]contained|"
    r"(?:whole|entire) (?:flat|apartment|place))\b",
    _I,
)


@dataclass(frozen=True)
class RentQuote:
    """The rent being asked and where we read it."""

    rent: int
    source: str  # evidence id, or "listing"
    quote: str


@lru_cache
def load_area_rents(path: Path = RENTS_PATH) -> dict[str, dict[str, int]]:
    """District -> {"room": £, "one_bed": £}. Approximate, hand-built figures."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {str(k).upper(): {kind: int(v) for kind, v in row.items()} for k, row in raw.items()}


def district_of(case: Case) -> str | None:
    """The postcode district (e.g. `W12`) from the listing, or else the first one in the chat."""
    listing = case.listing
    candidates = [listing.postcode, listing.address] if listing else []
    candidates += [m.text for m in case.messages]
    for text in candidates:
        if text and (m := _POSTCODE.search(text)):
            return m.group(1).upper()
    return None


def rent_of(case: Case) -> RentQuote | None:
    """The monthly rent from the listing, or else the first one the agent states."""
    if case.listing and case.listing.rent_pcm:
        rent = case.listing.rent_pcm
        return RentQuote(rent, "listing", f"£{rent:,} pcm")
    for m in case.messages:
        if m.sender == "agent" and (found := _RENT.search(m.text)):
            return RentQuote(round(float(found.group(1).replace(",", ""))), m.evidence_id, found[0])
    return None


def property_kind(case: Case) -> Kind:
    """`one_bed` only when the text clearly says a whole flat; otherwise compare as a room."""
    parts = [m.text for m in case.messages]
    if case.listing:
        parts += [case.listing.description or "", case.listing.address or ""]
    text = " ".join(parts)
    if _ROOM.search(text):
        return "room"
    return "one_bed" if _WHOLE_FLAT.search(text) else "room"


def price_finding(case: Case) -> Finding | None:
    """One fair_price finding, or None when rent or district is unknown or not in the table."""
    quote, district = rent_of(case), district_of(case)
    if quote is None or district is None or district not in load_area_rents():
        return None
    kind = property_kind(case)
    typical = load_area_rents()[district][kind]
    diff = (quote.rent - typical) / typical
    label = "a room" if kind == "room" else "a one-bed flat"
    compared = (
        f"£{quote.rent:,} a month against roughly £{typical:,} for {label} in {district} "
        f"(approximate area figure)"
    )
    if diff <= FAR_BELOW:
        severity, supports, confidence = Severity.MEDIUM, "suspicious", 0.6
        title = "Rent well below the area average"
        detail = (
            f"{compared}: about {abs(diff):.0%} lower. Prices far below the area are a common lure."
        )
    elif abs(diff) <= IN_LINE:
        severity, supports, confidence = Severity.INFO, "cleared", 0.6
        title = "Rent in line with the area"
        detail = f"{compared}."
    elif diff < 0:
        severity, supports, confidence = Severity.LOW, "suspicious", 0.6
        title = "Rent somewhat below the area average"
        detail = f"{compared}: about {abs(diff):.0%} lower."
    else:
        severity, supports, confidence = Severity.INFO, "suspicious", 0.6
        title = "Rent above the area average"
        detail = f"{compared}: about {diff:.0%} higher. Not a scam sign, but worth knowing."
    return Finding(
        id=f"{AGENT}:rent_vs_area",
        agent=AGENT,
        check_id=CheckId.FAIR_PRICE,
        title=title,
        detail=detail,
        category=Category.PRICING,
        severity=severity,
        confidence=confidence,
        evidence=[EvidenceRef(evidence_id=quote.source, quote=quote.quote)],
        supports=supports,  # type: ignore[arg-type]
    )
