"""Case fields the student states in a reply (plan 4.7): validate, normalise, then apply.

Pure functions. `read_fields` runs inside `conversation.read_reply` (no lock); `apply_fields`
runs in the service under the state lock, on the latest stored case.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.contracts import Case, Landlord, Listing
from app.orchestrator.composer import RoundNote
from app.orchestrator.models import FieldName, LLMFieldUpdate

MAX_QUOTE_CHARS = 200

# Human labels, used in round notes. Never carry the value of a company number (8 digits would
# break the composer's digit rule, and it is an identifier).
FIELD_LABELS: dict[FieldName, str] = {
    "landlord.company_number": "company number",
    "landlord.name": "landlord name",
    "listing.rent_pcm": "rent",
    "listing.deposit": "deposit",
    "student.move_in_date": "move-in date",
}

MIN_POUNDS = 50
MAX_POUNDS = 20_000
MIN_NAME_CHARS = 2
MAX_NAME_CHARS = 80
DAYS_BEFORE_TODAY = 30
DAYS_AFTER_TODAY = 365

MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
# Full and 3-letter month names, lower-cased, to month number.
_MONTH_NUMBERS = {
    name: number
    for number, month in enumerate(MONTHS, start=1)
    for name in (month.lower(), month[:3].lower())
}

# ASCII digits only: `\d` would also accept other scripts' digits.
_COMPANY_NUMBER = re.compile(r"(?:[A-Z]{2}\d{6}|\d{1,8})", re.ASCII)
# "1,250" (strict thousands groups) or "1250", with optional pence ".00".
_POUNDS = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?", re.ASCII)
_THOUSANDS = re.compile(r"(\d+(?:\.\d+)?)k", re.ASCII)
_PER_MONTH = re.compile(r"\s*(?:pcm|pm|p/m|/pcm|/month|per month|a month)$")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
_DAY_MONTH_YEAR = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\s+(\d{4})", re.ASCII)

# Curly quotes and apostrophes the LLM (or the student's keyboard) may use instead of straight ones.
_QUOTE_MAP = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


@dataclass(frozen=True)
class FieldUpdate:
    """A validated, normalised case field taken from the reply."""

    field: FieldName
    value: str | int | date
    correction: bool = False  # the student explicitly corrects a value we already hold


def normalise(text: str) -> str:
    """Straight quotes, single spaces, case-folded: the form quotes are compared in."""
    return " ".join(text.translate(_QUOTE_MAP).split()).casefold()


def quote_found(quote: str, text: str) -> bool:
    """True when `quote` is a non-empty, short span of the student's `text`."""
    needle = normalise(quote)
    return bool(needle) and len(needle) <= MAX_QUOTE_CHARS and needle in normalise(text)


def parse_company_number(value: str) -> str | None:
    """Upper-cased, spaces removed, all-digit numbers zero-padded to 8; None when invalid."""
    compact = "".join(value.split()).upper()
    if not _COMPANY_NUMBER.fullmatch(compact):
        return None
    return compact.zfill(8) if compact.isdigit() else compact


def parse_name(value: str) -> str | None:
    """The stripped name when it is 2 to 80 characters with a letter; None otherwise."""
    name = value.strip()
    if not MIN_NAME_CHARS <= len(name) <= MAX_NAME_CHARS:
        return None
    return name if any(c.isalpha() for c in name) else None


def _amount(text: str) -> Decimal | None:
    """The amount in "1,250", "1250.00" or "1.25k" form; None for anything else."""
    if match := _THOUSANDS.fullmatch(text):
        return Decimal(match[1]) * 1000
    if match := _POUNDS.fullmatch(text):
        return Decimal(match[1].replace(",", "") + "." + (match[2] or "0"))
    return None


def parse_pounds(value: str) -> int | None:
    """Whole pounds in 50 to 20000 from "£1,250", "1.25k" or "950 pcm"; None when ambiguous."""
    text = _PER_MONTH.sub("", value.strip().lower()).removeprefix("£").strip()
    amount = _amount(text)
    if amount is None or amount != amount.to_integral_value():
        return None  # pence or a fraction of a pound: not a plain rent or deposit
    pounds = int(amount)
    return pounds if MIN_POUNDS <= pounds <= MAX_POUNDS else None


def _calendar_date(text: str) -> date | None:
    """A date in ISO or "1 March 2027" / "1st Mar 2027" form; None for anything else."""
    try:
        if _ISO_DATE.fullmatch(text):
            return date.fromisoformat(text)
        if match := _DAY_MONTH_YEAR.fullmatch(text.lower()):
            month = _MONTH_NUMBERS.get(match[2])
            return date(int(match[3]), month, int(match[1])) if month else None
    except ValueError:  # e.g. 31 February
        return None
    return None


def parse_move_in(value: str, today: date) -> date | None:
    """The move-in date when it is 30 days before to 365 days after `today`; None otherwise."""
    moved_in = _calendar_date(" ".join(value.split()))
    if moved_in is None:
        return None
    earliest = today - timedelta(days=DAYS_BEFORE_TODAY)
    latest = today + timedelta(days=DAYS_AFTER_TODAY)
    return moved_in if earliest <= moved_in <= latest else None


def _normalised_value(field: FieldName, value: str, today: date) -> str | int | date | None:
    """The field's value in its case form, or None when it fails validation."""
    match field:
        case "landlord.company_number":
            return parse_company_number(value)
        case "landlord.name":
            return parse_name(value)
        case "listing.rent_pcm" | "listing.deposit":
            return parse_pounds(value)
        case "student.move_in_date":
            return parse_move_in(value, today)


def read_fields(
    raw: Sequence[LLMFieldUpdate], text: str, today: date
) -> tuple[tuple[FieldUpdate, ...], tuple[str, ...]]:
    """Validate the LLM's field readings against the reply.

    Returns (valid updates, labels of fields the student gave but we could not use). A reading
    whose quote is not in `text` is dropped without a label (the LLM made it up). At most one
    update per field (the first valid one).
    """
    valid: dict[FieldName, FieldUpdate] = {}
    invalid: list[FieldName] = []
    for reading in raw:
        if reading.field in valid or not quote_found(reading.quote, text):
            continue
        value = _normalised_value(reading.field, reading.value, today)
        if value is None:
            invalid.append(reading.field)
        else:
            valid[reading.field] = FieldUpdate(reading.field, value, reading.correction)
    # A field that also had a valid reading was usable after all.
    labels = dict.fromkeys(FIELD_LABELS[f] for f in invalid if f not in valid)
    return tuple(valid.values()), tuple(labels)


def _current(case: Case, field: FieldName) -> str | int | date | None:
    """The value the case holds for `field` (None when empty)."""
    landlord, listing = case.landlord, case.listing
    values: dict[FieldName, str | int | date | None] = {
        "landlord.company_number": landlord.company_number if landlord else None,
        "landlord.name": landlord.name if landlord else None,
        "listing.rent_pcm": listing.rent_pcm if listing else None,
        "listing.deposit": listing.deposit if listing else None,
        "student.move_in_date": case.student.move_in_date,
    }
    value = values[field]
    return None if value == "" else value


def _landlord(case: Case) -> Landlord:
    if case.landlord is None:
        case.landlord = Landlord()
    return case.landlord


def _listing(case: Case) -> Listing:
    if case.listing is None:
        case.listing = Listing()
    return case.listing


def _write(case: Case, update: FieldUpdate) -> None:
    """Store `update.value` in its place on `case`. A value of the wrong type is a bug."""
    match update.field, update.value:
        case "landlord.company_number", str(value):
            _landlord(case).company_number = value
        case "landlord.name", str(value):
            _landlord(case).name = value
        case "listing.rent_pcm", int(value):
            _listing(case).rent_pcm = value
        case "listing.deposit", int(value):
            _listing(case).deposit = value
        case "student.move_in_date", date() as value:
            case.student.move_in_date = value
        case field, value:
            raise TypeError(f"{field} cannot hold a {type(value).__name__}")


def _format_date(value: date) -> str:
    """Format as "1 March 2027": day without a leading zero, full month name, year."""
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def change_note(update: FieldUpdate) -> RoundNote:
    """The `field_changed` note for an applied update. Never carries a company number."""
    field, value = update.field, update.value
    if field == "landlord.company_number":
        text = FIELD_LABELS[field]  # the label only, never the digits
    elif field == "landlord.name":
        text = "landlord name updated"
    elif isinstance(value, date):
        text = f"move-in date set to {_format_date(value)}"
    else:
        text = f"{FIELD_LABELS[field]} set to {value}"
    return RoundNote(kind="field_changed", text=text)


def apply_fields(case: Case, updates: Sequence[FieldUpdate]) -> list[RoundNote]:
    """Write updates into `case` (mutates it) and return one `field_changed` note per change.

    A field is written only when it is empty, or when the update is a correction. Writing the
    value already held is not a change. Creates `case.landlord` / `case.listing` when missing.
    """
    notes: list[RoundNote] = []
    for update in updates:
        current = _current(case, update.field)
        if current == update.value or (current is not None and not update.correction):
            continue
        _write(case, update)
        notes.append(change_note(update))
    return notes
