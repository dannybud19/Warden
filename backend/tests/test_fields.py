"""Case fields from a reply: `read_fields` validation and `apply_fields` writes and notes."""

import re
from datetime import UTC, date, datetime, timedelta

import pytest

from app.contracts import Case, Landlord, Listing
from app.orchestrator.composer import RoundNote
from app.orchestrator.fields import FieldUpdate, apply_fields, read_fields
from app.orchestrator.models import FieldName, LLMFieldUpdate

TODAY = date(2026, 11, 14)


def reading(
    field: FieldName, value: str, quote: str | None = None, correction: bool = False
) -> LLMFieldUpdate:
    return LLMFieldUpdate(field=field, value=value, quote=quote or value, correction=correction)


def read_one(field: FieldName, value: str) -> tuple[tuple[FieldUpdate, ...], tuple[str, ...]]:
    """Read one field whose value is also its quote and the whole reply."""
    return read_fields([reading(field, value)], value, TODAY)


def value_of(field: FieldName, value: str) -> str | int | date | None:
    updates, _ = read_one(field, value)
    return updates[0].value if updates else None


def make_case(**kwargs: object) -> Case:
    return Case.model_validate(
        {"case_id": "c1", "created_at": datetime(2026, 11, 14, tzinfo=UTC), **kwargs}
    )


def notes(*texts: str) -> list[RoundNote]:
    return [RoundNote(kind="field_changed", text=t) for t in texts]


# read_fields: company number


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("01234567", "01234567"),
        ("1234567", "01234567"),
        ("12 34 56 78", "12345678"),
        ("sc123456", "SC123456"),
        ("OC 123456", "OC123456"),
    ],
)
def test_company_number_is_normalised(value: str, expected: str) -> None:
    assert value_of("landlord.company_number", value) == expected


@pytest.mark.parametrize("value", ["123456789", "S1234567", "SC12345", "ABC12345", "12-34", ""])
def test_bad_company_number_is_invalid(value: str) -> None:
    text = f"the number is {value}"
    raw = [reading("landlord.company_number", value, quote="the number is")]
    assert read_fields(raw, text, TODAY) == ((), ("company number",))


# read_fields: landlord name


def test_landlord_name_is_stripped() -> None:
    raw = [reading("landlord.name", "  Smith Lettings Ltd ", quote="Smith Lettings Ltd")]
    updates, _ = read_fields(raw, "it's Smith Lettings Ltd", TODAY)
    assert updates == (FieldUpdate("landlord.name", "Smith Lettings Ltd"),)


@pytest.mark.parametrize("value", ["J", "  ", "1234", "x" * 81])
def test_bad_landlord_name_is_invalid(value: str) -> None:
    raw = [reading("landlord.name", value, quote="the landlord")]
    assert read_fields(raw, "the landlord", TODAY) == ((), ("landlord name",))


def test_landlord_name_length_edges() -> None:
    assert value_of("landlord.name", "Jo") == "Jo"
    assert value_of("landlord.name", "x" * 80) == "x" * 80


# read_fields: rent and deposit


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("£1,250", 1250),
        ("1250", 1250),
        ("1,250.00", 1250),
        ("1.25k", 1250),
        ("1.25K", 1250),
        ("950 pcm", 950),
        ("£950pcm", 950),
        ("950 per month", 950),
        ("£ 950", 950),
        ("50", 50),
        ("20000", 20000),
        ("£20,000", 20000),
    ],
)
@pytest.mark.parametrize("field", ["listing.rent_pcm", "listing.deposit"])
def test_money_is_whole_pounds(field: FieldName, value: str, expected: int) -> None:
    assert value_of(field, value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "49",
        "20001",
        "950.50",
        "1,25",
        "12,50",
        "1.2345k",
        "900-950",
        "about 950",
        "950 or 1000",
        "£",
        "nine hundred",
        "-950",
    ],
)
def test_ambiguous_or_out_of_range_money_is_invalid(value: str) -> None:
    raw = [reading("listing.rent_pcm", value, quote="the rent")]
    assert read_fields(raw, "the rent", TODAY) == ((), ("rent",))


def test_invalid_deposit_has_its_own_label() -> None:
    raw = [reading("listing.deposit", "lots", quote="deposit")]
    assert read_fields(raw, "deposit", TODAY) == ((), ("deposit",))


# read_fields: move-in date


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2027-03-01", date(2027, 3, 1)),
        ("1 March 2027", date(2027, 3, 1)),
        ("1st March 2027", date(2027, 3, 1)),
        ("1st mar 2027", date(2027, 3, 1)),
        ("22nd Dec 2026", date(2026, 12, 22)),
        ("3 September  2027", date(2027, 9, 3)),
    ],
)
def test_move_in_date_is_parsed(value: str, expected: date) -> None:
    assert value_of("student.move_in_date", value) == expected


@pytest.mark.parametrize(
    "value", ["01/03/2027", "March 1 2027", "1 Marzo 2027", "31 February 2027", "next week"]
)
def test_bad_move_in_date_is_invalid(value: str) -> None:
    raw = [reading("student.move_in_date", value, quote="I move in")]
    assert read_fields(raw, "I move in", TODAY) == ((), ("move-in date",))


@pytest.mark.parametrize(
    ("days", "valid"), [(-31, False), (-30, True), (0, True), (365, True), (366, False)]
)
def test_move_in_date_window_edges(days: int, valid: bool) -> None:
    value = (TODAY + timedelta(days=days)).isoformat()
    updates, invalid = read_one("student.move_in_date", value)
    assert bool(updates) is valid
    assert invalid == (() if valid else ("move-in date",))


# read_fields: quotes, one per field, labels


def test_quote_not_in_text_is_dropped_without_a_label() -> None:
    raw = [reading("listing.rent_pcm", "950", quote="rent is 950")]
    assert read_fields(raw, "the deposit is 950", TODAY) == ((), ())


def test_bad_value_with_a_made_up_quote_is_dropped_without_a_label() -> None:
    raw = [reading("listing.rent_pcm", "lots", quote="not said")]
    assert read_fields(raw, "the rent is lots", TODAY) == ((), ())


def test_quote_matches_after_normalising_quotes_and_case() -> None:
    raw = [reading("landlord.name", "O'Brien Homes", quote="it’s O’BRIEN homes")]
    updates, _ = read_fields(raw, "It's O'Brien Homes", TODAY)
    assert [u.value for u in updates] == ["O'Brien Homes"]


def test_first_valid_reading_per_field_wins() -> None:
    text = "rent is 950, or maybe 1000"
    raw = [
        reading("listing.rent_pcm", "950", quote="rent is 950"),
        reading("listing.rent_pcm", "1000", quote="maybe 1000"),
    ]
    assert read_fields(raw, text, TODAY) == ((FieldUpdate("listing.rent_pcm", 950),), ())


def test_invalid_then_valid_reading_keeps_the_valid_one_without_a_label() -> None:
    text = "rent is about 950, it's 950 pcm"
    raw = [
        reading("listing.rent_pcm", "about 950", quote="about 950"),
        reading("listing.rent_pcm", "950 pcm", quote="950 pcm"),
    ]
    assert read_fields(raw, text, TODAY) == ((FieldUpdate("listing.rent_pcm", 950),), ())


def test_invalid_labels_are_deduplicated_in_order() -> None:
    text = "deposit is lots, rent is loads, rent is heaps"
    raw = [
        reading("listing.deposit", "lots", quote="deposit is lots"),
        reading("listing.rent_pcm", "loads", quote="rent is loads"),
        reading("listing.rent_pcm", "heaps", quote="rent is heaps"),
    ]
    assert read_fields(raw, text, TODAY) == ((), ("deposit", "rent"))


def test_correction_is_kept_and_fields_keep_reading_order() -> None:
    text = "actually the rent is 950 and I move in on 1 March 2027"
    raw = [
        reading("student.move_in_date", "1 March 2027"),
        reading("listing.rent_pcm", "950", quote="actually the rent is 950", correction=True),
    ]
    updates, invalid = read_fields(raw, text, TODAY)
    assert updates == (
        FieldUpdate("student.move_in_date", date(2027, 3, 1)),
        FieldUpdate("listing.rent_pcm", 950, correction=True),
    )
    assert invalid == ()


def test_no_readings() -> None:
    assert read_fields([], "hello", TODAY) == ((), ())


# apply_fields


def test_fills_empty_fields_and_creates_landlord_and_listing() -> None:
    case = make_case()
    updates = [
        FieldUpdate("landlord.company_number", "01234567"),
        FieldUpdate("landlord.name", "Smith Lettings"),
        FieldUpdate("listing.rent_pcm", 950),
        FieldUpdate("listing.deposit", 1200),
        FieldUpdate("student.move_in_date", date(2027, 3, 1)),
    ]

    result = apply_fields(case, updates)

    assert case.landlord == Landlord(company_number="01234567", name="Smith Lettings")
    assert case.listing == Listing(rent_pcm=950, deposit=1200)
    assert case.student.move_in_date == date(2027, 3, 1)
    assert result == notes(
        "company number",
        "landlord name updated",
        "rent set to 950",
        "deposit set to 1200",
        "move-in date set to 1 March 2027",
    )


def test_company_number_note_has_no_digits() -> None:
    case = make_case(landlord={"name": "Smith Lettings"})
    (note,) = apply_fields(case, [FieldUpdate("landlord.company_number", "SC123456")])
    assert note.text == "company number"
    assert not re.search(r"\d", note.text)
    assert case.landlord == Landlord(name="Smith Lettings", company_number="SC123456")


def test_held_value_is_not_overwritten_without_a_correction() -> None:
    case = make_case(listing={"rent_pcm": 1000}, landlord={"name": "Old Name"})
    updates = [FieldUpdate("listing.rent_pcm", 950), FieldUpdate("landlord.name", "New Name")]
    assert apply_fields(case, updates) == []
    assert case.listing == Listing(rent_pcm=1000)
    assert case.landlord == Landlord(name="Old Name")


def test_correction_overwrites_a_held_value() -> None:
    case = make_case(listing={"rent_pcm": 1000}, student={"move_in_date": "2027-01-01"})
    updates = [
        FieldUpdate("listing.rent_pcm", 950, correction=True),
        FieldUpdate("student.move_in_date", date(2027, 2, 5), correction=True),
    ]
    assert apply_fields(case, updates) == notes(
        "rent set to 950", "move-in date set to 5 February 2027"
    )
    assert case.listing == Listing(rent_pcm=950)
    assert case.student.move_in_date == date(2027, 2, 5)


def test_unchanged_value_is_not_a_change() -> None:
    case = make_case(listing={"deposit": 1200}, landlord={"company_number": "01234567"})
    updates = [
        FieldUpdate("listing.deposit", 1200, correction=True),
        FieldUpdate("landlord.company_number", "01234567"),
    ]
    assert apply_fields(case, updates) == []


def test_empty_string_counts_as_empty() -> None:
    case = make_case(landlord={"name": ""})
    assert apply_fields(case, [FieldUpdate("landlord.name", "Smith")]) == notes(
        "landlord name updated"
    )
    assert case.landlord == Landlord(name="Smith")


def test_skipped_update_does_not_create_a_listing() -> None:
    case = make_case(listing=None, student={"move_in_date": "2027-01-01"})
    assert apply_fields(case, [FieldUpdate("student.move_in_date", date(2027, 2, 1))]) == []
    assert case.listing is None and case.landlord is None


def test_existing_listing_keeps_its_other_fields() -> None:
    case = make_case(listing={"address": "1 High St", "rent_pcm": 900})
    apply_fields(case, [FieldUpdate("listing.deposit", 1200)])
    assert case.listing == Listing(address="1 High St", rent_pcm=900, deposit=1200)


def test_wrong_value_type_is_a_bug() -> None:
    with pytest.raises(TypeError, match="listing.rent_pcm cannot hold a str"):
        apply_fields(make_case(), [FieldUpdate("listing.rent_pcm", "950")])
