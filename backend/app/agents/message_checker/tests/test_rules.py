"""One test per rule, on small hand-written chats."""

from datetime import UTC, datetime

import pytest

from app.agents.message_checker import rules
from app.contracts import Case, FactKey, Landlord, Message


def chat(*lines: str) -> Case:
    """`"a: text"` is an agent message, `"s: text"` a student one."""
    messages = [
        Message(
            id=f"msg_{i}",
            evidence_id="ev_1",
            sender="agent" if line.startswith("a:") else "student",
            channel="whatsapp",
            text=line[2:].strip(),
        )
        for i, line in enumerate(lines, 1)
    ]
    return Case(case_id="c1", created_at=datetime.now(UTC), messages=messages)


def by_id(case: Case) -> dict:
    return {f.id.split(":")[1]: f for f in rules.run_rules(case).findings}


def test_payment_before_viewing_explicit_is_hard() -> None:
    found = by_id(chat("s: Can I view it?", "a: Send the deposit today to hold it."))
    f = found["payment_before_viewing"]
    assert f.hard_flag and f.severity == "critical" and f.confidence == 0.9
    assert f.evidence[0].quote == "Send the deposit today to hold it."


def test_payment_before_viewing_without_refusal_is_not_hard() -> None:
    f = by_id(chat("a: Please transfer the first month's rent by Friday."))[
        "payment_before_viewing"
    ]
    assert not f.hard_flag and f.confidence == 0.7


def test_no_payment_flag_after_a_viewing() -> None:
    found = by_id(
        chat(
            "a: Thanks for coming today.",
            "a: We take a holding deposit of £200 through our online portal.",
        )
    )
    assert "payment_before_viewing" not in found
    assert found["viewing_completed"].supports == "cleared"
    assert found["payment_after_viewing_via_portal"].supports == "cleared"


def test_seeing_the_advert_is_not_a_viewing() -> None:
    case = chat("s: Hello, I saw your advert for the flat.", "a: Pay the deposit to secure it.")
    found = by_id(case)
    assert "viewing_completed" not in found
    assert found["payment_before_viewing"].hard_flag


def test_reassurance_about_payment_is_not_a_request() -> None:
    assert "payment_before_viewing" not in by_id(chat("a: You pay nothing until you have viewed."))


@pytest.mark.parametrize(
    "text",
    [
        "I only accept payment by Western Union.",
        "Buy Amazon gift cards and send me the codes.",
        "You can pay in Bitcoin.",
        "Load a pre-paid card with the deposit.",
    ],
)
def test_untraceable_payment_is_hard(text: str) -> None:
    f = by_id(chat(f"a: {text}"))["untraceable_payment"]
    assert f.hard_flag and f.severity == "critical"


def test_personal_emoney_transfer_but_not_to_a_company() -> None:
    assert "personal_emoney_transfer" in by_id(chat("a: Send the deposit to my Revolut."))
    company = chat("a: Pay the deposit to Larkfield Lettings Ltd, we bank with Revolut.")
    assert "personal_emoney_transfer" not in by_id(company)
    assert "personal_emoney_transfer" not in by_id(chat("a: It would be wise to decide soon."))


def test_overseas_bank_account() -> None:
    found = by_id(chat("a: Transfer the deposit to IBAN ES91 2100 0418 4502 0005 1332."))
    assert found["overseas_bank_account"].severity == "high"
    uk = chat("a: Transfer the deposit to IBAN GB29 NWBK 6016 1331 9268 19.")
    assert "overseas_bank_account" not in by_id(uk)


def test_lookalike_link() -> None:
    found = by_id(chat("a: Book here: https://airbnb-secure-rentals.com/room/123"))
    assert "airbnb-secure-rentals.com" in found["lookalike_link"].evidence[0].quote
    real = chat("a: The advert is at https://www.spareroom.co.uk/flatshare/123 and airbnb.com")
    assert "lookalike_link" not in by_id(real)


def test_overpayment_and_pose_as_buyer() -> None:
    assert "overpayment_refund" in by_id(chat("a: I overpaid, please refund the difference."))
    assert "pose_as_buyer" in by_id(chat("a: Send it as friends and family on PayPal."))
    assert "pose_as_buyer" in by_id(chat("a: Tell them you are a buyer if anyone asks."))


def test_landlord_abroad_and_viewing_refused() -> None:
    found = by_id(
        chat(
            "s: Could I see it this weekend?",
            "a: I’m overseas for work, I will post the keys.",
            "a: That is not possible I'm afraid.",
        )
    )
    assert found["landlord_abroad"].severity == "high"
    assert found["viewing_refused"].evidence[0].quote == "That is not possible I'm afraid."
    # the quote is taken from the original text, curly apostrophe included
    assert "I’m overseas" in found["landlord_abroad"].evidence[0].quote


def test_off_platform_move_is_low() -> None:
    assert by_id(chat("a: Email me directly, it's easier."))["off_platform_move"].severity == "low"


def test_viewing_offered_clears_weakly_and_refusal_blocks_it() -> None:
    f = by_id(chat("a: We have viewing slots on Saturday at 10:30."))["viewing_offered"]
    assert f.supports == "cleared" and f.confidence == 0.4
    blocked = chat("a: We have viewing slots on Saturday at 10:30.", "a: Sorry, no viewings now.")
    assert "viewing_offered" not in by_id(blocked)


def test_deposit_scheme_named() -> None:
    f = by_id(chat("a: Your deposit is registered with the DPS."))["deposit_scheme_named"]
    assert f.check_id == "deposit_protection" and f.supports == "cleared"


def test_facts() -> None:
    case = chat(
        "s: Is Flat 3, 12 Elm Road, London W12 8QT free?",
        "a: Yes. Rent is £1,250.00 pcm, deposit of £1,442. Holding deposit of £288.",
        "a: Sort code 12-34-56, account 00001234. Email lets@prime-city.example.co.uk",
    )
    case.landlord = Landlord(email="mark@example.org")
    facts = {(f.key, f.value) for f in rules.extract_facts(case)}
    assert (FactKey.ADDRESS, "Flat 3, 12 Elm Road, London W12 8QT") in facts
    assert (FactKey.RENT_PCM, "1250") in facts
    assert (FactKey.DEPOSIT, "1442") in facts
    assert (FactKey.BANK_ACCOUNT, "sort **-**-56, account ****1234") in facts
    assert (FactKey.EMAIL_DOMAIN, "prime-city.example.co.uk") in facts
    assert (FactKey.EMAIL_DOMAIN, "example.org") in facts
    assert not any("00001234" in value for _, value in facts)


def test_quotes_are_exact_substrings_and_short() -> None:
    case = chat("a: " + "Very long preamble " * 20 + "send the deposit by Western Union now.")
    for f in rules.run_rules(case).findings:
        for ref in f.evidence:
            assert ref.quote and len(ref.quote) <= 200
            assert ref.quote in case.messages[0].text
