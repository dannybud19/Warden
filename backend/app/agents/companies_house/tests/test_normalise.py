from datetime import date

from app.agents.companies_house.normalise import (
    domain_of,
    extract_contacts,
    extract_postcode,
    months_between,
    name_score,
    normalise_name,
    normalise_number,
    normalise_phone,
    normalise_postcode,
    parse_dob,
    person_matches_officer,
    slug,
    split_officer_name,
    strip_title,
    url_hash8,
)
from app.contracts import Case, Landlord, Listing


def test_number_padding_and_prefixes() -> None:
    assert normalise_number("1234567") == "01234567"
    assert normalise_number(" 09 123 456 ") == "09123456"
    assert normalise_number("sc123456") == "SC123456"
    assert normalise_number("NI012345") == "NI012345"
    assert normalise_number("OC301234") == "OC301234"


def test_name_normalisation() -> None:
    assert normalise_name("The Larkfield & Co. Lettings Ltd") == "larkfield and lettings"
    assert normalise_name("PRIME CITY LETTINGS LIMITED") == "prime city lettings"
    assert normalise_name("Foo UK Ltd") == "foo"


def test_name_score() -> None:
    assert name_score("Prime City Lettings Ltd", "PRIME CITY LETTINGS LIMITED") == 100
    assert name_score("Prime City Lettings", "Totally Different Homes") < 50
    assert name_score("", "") == 0


def test_slug_and_hash_are_stable() -> None:
    assert slug("Hello, World! It's 2026") == "hello-world-it-s-2026"
    assert len(slug("a" * 100)) == 40
    assert url_hash8("https://x.test/a") == url_hash8("https://x.test/a")
    assert len(url_hash8("https://x.test/a")) == 8
    assert url_hash8("https://x.test/a") != url_hash8("https://x.test/b")


def test_domain_of() -> None:
    assert domain_of("Agent@Example.CO.UK") == "example.co.uk"
    assert domain_of("https://www.Rightmove.co.uk/x?y=1") == "rightmove.co.uk"
    assert domain_of("www.example.com") == "example.com"


def test_months_between() -> None:
    today = date(2026, 11, 14)
    assert months_between(date(2026, 6, 1), today) == 5
    assert months_between(date(2025, 11, 14), today) == 12
    assert months_between(date(2025, 11, 15), today) == 11
    assert months_between(date(2014, 7, 3), today) == 148


def test_officer_names() -> None:
    assert split_officer_name("CLARKE, Hannah Louise") == ("clarke", ["hannah", "louise"])
    assert split_officer_name("Hannah Clarke") == ("clarke", ["hannah"])
    assert split_officer_name("") == ("", [])
    assert strip_title("Mr Mark Evans") == "Mark Evans"
    assert strip_title("Dr. Jane Roe") == "Jane Roe"


def test_person_matches_officer() -> None:
    assert person_matches_officer("Hannah Clarke", "CLARKE, Hannah Louise")
    assert person_matches_officer("H Clarke", "CLARKE, Hannah Louise")
    assert person_matches_officer("Mr Mark Evans", "EVANS, Mark")
    assert not person_matches_officer("Sam Patel", "CLARKE, Hannah Louise")
    assert not person_matches_officer("Tom Clarke", "CLARKE, Hannah Louise")


def test_parse_dob_is_defensive() -> None:
    assert parse_dob({"month": 4, "year": 1985}) == (1985, 4)
    assert parse_dob("1985-04-12") == (1985, 4)
    assert parse_dob("1985-04") == (1985, 4)
    assert parse_dob("1985") == (1985, None)
    assert parse_dob(None) is None
    assert parse_dob("garbage") is None
    assert parse_dob({"year": "x"}) is None
    assert parse_dob({"year": 1985, "month": 13}) == (1985, None)


def test_postcodes() -> None:
    assert normalise_postcode("w128qt") == "W12 8QT"
    assert normalise_postcode(" se1  7lp ") == "SE1 7LP"
    assert extract_postcode(Listing(postcode="se17lp")) == "SE1 7LP"
    assert (
        extract_postcode(Listing(address="Flat 5, 21 Mercer Street, London se1 7lp")) == "SE1 7LP"
    )
    assert extract_postcode(Listing(address="Somewhere")) is None
    assert extract_postcode(None) is None


def test_partial_or_free_text_postcode_is_not_looked_up() -> None:
    assert extract_postcode(Listing(postcode="W12")) is None
    assert extract_postcode(Listing(postcode="London")) is None
    # a bad postcode field falls back to a full postcode in the address
    assert extract_postcode(Listing(postcode="W12", address="3 Road, London W12 8QT")) == "W12 8QT"


def test_phone_normalisation() -> None:
    assert normalise_phone("07911 123456") == "07911123456"
    assert normalise_phone("+44 7911 123456") == "07911123456"
    assert normalise_phone("020 7946 0958") == "02079460958"
    assert normalise_phone("0161 496 0000") is None


def _case(**kwargs: object) -> Case:
    return Case.model_validate(
        {"case_id": "c1", "created_at": "2026-11-14T10:00:00", "student": {}, **kwargs}
    )


def _msg(i: int, sender: str, text: str) -> dict[str, object]:
    return {"id": f"m{i}", "evidence_id": "ev1", "sender": sender, "channel": "email", "text": text}


def test_contacts_prefer_landlord_fields() -> None:
    case = _case(
        landlord=Landlord(email="Lets@Agency.co.uk", phone="07911 123456").model_dump(),
        messages=[_msg(1, "agent", "mail other@x.com")],
    )
    c = extract_contacts(case)
    assert c.emails == ["lets@agency.co.uk"]
    assert c.phones == ["07911123456"]


def test_contacts_from_agent_messages_only() -> None:
    case = _case(
        landlord={"company_name": "X Ltd"},
        messages=[
            _msg(1, "student", "my email is me@student.ac.uk call 07700 900123"),
            _msg(
                2, "agent", "Email a@one.com or b@two.com or c@three.com, call +44 7911 123456 now"
            ),
        ],
    )
    c = extract_contacts(case)
    assert c.emails == ["a@one.com", "b@two.com"]  # max 2
    assert c.phones == ["07911123456"]
    assert "me@student.ac.uk" not in c.emails
    assert c.keys() == ["email:a@one.com", "email:b@two.com", "phone:07911123456"]
