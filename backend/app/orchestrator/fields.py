"""Case fields the student states in a reply (plan 4.7): validate, normalise, then apply.

Pure functions. `read_fields` runs inside `conversation.parse` (no lock); `apply_fields` runs in the
service under the state lock, on the latest stored case.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.contracts import Case
from app.orchestrator.composer import RoundNote
from app.orchestrator.models import FieldName, LLMFieldUpdate

# Human labels, used in round notes. Never carry the value of a company number (8 digits would
# break the composer's digit rule, and it is an identifier).
FIELD_LABELS: dict[FieldName, str] = {
    "landlord.company_number": "company number",
    "landlord.name": "landlord name",
    "listing.rent_pcm": "rent",
    "listing.deposit": "deposit",
    "student.move_in_date": "move-in date",
}


@dataclass(frozen=True)
class FieldUpdate:
    """A validated, normalised case field taken from the reply."""

    field: FieldName
    value: str | int | date
    correction: bool = False  # the student explicitly corrects a value we already hold


def read_fields(
    raw: Sequence[LLMFieldUpdate], text: str, today: date
) -> tuple[tuple[FieldUpdate, ...], tuple[str, ...]]:
    """Validate the LLM's field readings against the reply.

    Returns (valid updates, labels of fields the student gave but we could not use). A reading
    whose quote is not in `text` is dropped without a label (the LLM made it up). At most one
    update per field (the first valid one).
    """
    raise NotImplementedError


def apply_fields(case: Case, updates: Sequence[FieldUpdate]) -> list[RoundNote]:
    """Write updates into `case` (mutates it) and return one `field_changed` note per change.

    A field is written only when it is empty, or when the update is a correction. Writing the
    value already held is not a change. Creates `case.landlord` / `case.listing` when missing.
    """
    raise NotImplementedError
