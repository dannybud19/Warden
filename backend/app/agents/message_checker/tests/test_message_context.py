"""Regression contrasts: the same keywords can assert, deny or merely discuss a concern."""

from datetime import UTC, datetime

import pytest

from app.agents.message_checker.llm import convert
from app.agents.message_checker.models import LLMOutput
from app.agents.message_checker.rules import run_rules
from app.contracts import Case, Message


def chat(*lines: str) -> Case:
    return Case(
        case_id="context",
        created_at=datetime(2026, 11, 14, tzinfo=UTC),
        messages=[
            Message(
                id=f"m{i}",
                evidence_id="ev_chat",
                sender="student" if line.startswith("s:") else "agent",
                text=line[2:].strip(),
                channel="whatsapp",
            )
            for i, line in enumerate(lines)
        ],
    )


def findings(case: Case) -> dict:
    return {f.id.split(":", 1)[1]: f for f in run_rules(case).findings}


@pytest.mark.parametrize(
    "text",
    [
        "We never request gift cards, voucher codes or card photos.",
        "Do not buy Amazon gift cards or send me codes.",
        "Your prepaid debit card is your choice for budgeting.",
        "You can use your prepaid debit card at the card terminal.",
        "Gift cards are a common scam.",
        "We do not accept Bitcoin.",
    ],
)
def test_payment_mentions_and_denials_are_not_demands(text: str) -> None:
    assert "untraceable_payment" not in findings(chat(f"a: {text}"))


@pytest.mark.parametrize(
    "text",
    [
        "We never request gift cards; pay the deposit in Bitcoin.",
        "Do not send Bitcoin, but buy Amazon gift cards and send the codes.",
        "No payment is required before viewing. Buy vouchers and send the codes now.",
    ],
)
def test_reassurance_does_not_hide_a_separate_demand(text: str) -> None:
    f = findings(chat(f"a: {text}"))["untraceable_payment"]
    assert f.hard_flag
    assert all(ref.quote in text for ref in f.evidence)


@pytest.mark.parametrize(
    "text",
    [
        "Transfer it now. I will not arrange a viewing until you pay.",
        "Payment must happen before any viewing and only through that link.",
        "Viewings are arranged only after payment.",
        "Once the deposit has cleared we can arrange a viewing.",
    ],
)
def test_explicit_order_is_a_payment_hard_flag_candidate(text: str) -> None:
    f = findings(chat(f"a: {text}"))["payment_before_viewing"]
    assert f.hard_flag and f.confidence == 0.9


@pytest.mark.parametrize(
    "text",
    [
        "No payment is required before the viewing.",
        "You pay nothing until you have viewed.",
        "Pay the deposit only after the viewing.",
        "After you have viewed the flat, transfer the deposit.",
        "Pay the deposit before signing, after viewing.",
    ],
)
def test_post_viewing_payment_does_not_become_pre_viewing(text: str) -> None:
    assert "payment_before_viewing" not in findings(chat(f"a: {text}"))


def test_ambiguous_timing_is_not_hard() -> None:
    assert not findings(chat("a: Please transfer the rent by Friday."))[
        "payment_before_viewing"
    ].hard_flag


def test_long_message_retains_the_actual_demand_in_its_quote() -> None:
    text = "A long unrelated preamble " * 20 + "send the deposit by Western Union now."
    f = findings(chat(f"a: {text}"))["untraceable_payment"]
    assert "Western Union" in f.evidence[0].quote
    assert len(f.evidence[0].quote) <= 200 and f.evidence[0].quote in text


@pytest.mark.parametrize(
    "extra",
    [
        "a: Your viewing with our local agent is booked on Saturday at 16:00.",
        "s: I viewed the flat in person yesterday with the local agent.",
    ],
)
def test_abroad_with_a_local_viewing_is_not_a_barrier(extra: str) -> None:
    case = chat("a: The owner is abroad for work.", extra)
    assert "landlord_abroad" not in findings(case)
    output = LLMOutput.model_validate(
        {
            "flags": [
                {
                    "flag": "landlord_abroad",
                    "message_id": "m0",
                    "quote": "The owner is abroad for work.",
                    "confidence": 0.9,
                }
            ]
        }
    )
    assert not convert(output, case, set()).findings


def test_abroad_alone_is_not_proof_of_refused_access() -> None:
    assert "landlord_abroad" not in findings(chat("a: The owner is abroad."))


@pytest.mark.parametrize(
    "extra",
    [
        "a: My agent can show you round.",
        "s: I viewed the flat in person yesterday with the local agent.",
    ],
)
def test_local_access_explains_the_absent_owners_personal_refusal(extra: str) -> None:
    case = chat("a: I am overseas and cannot show the flat myself.", extra)
    assert "landlord_abroad" not in findings(case)
    output = LLMOutput.model_validate(
        {
            "flags": [
                {
                    "flag": "landlord_abroad",
                    "message_id": "m0",
                    "quote": case.messages[0].text,
                    "confidence": 0.9,
                }
            ]
        }
    )
    assert not convert(output, case, set()).findings


def test_abroad_with_an_actual_refusal_still_warns() -> None:
    found = findings(chat("a: I am overseas and cannot show the flat. I will post the keys."))
    assert {"landlord_abroad", "viewing_refused"} <= set(found)


def test_llm_cannot_reintroduce_a_denied_method_or_student_question() -> None:
    case = chat("a: We never request gift cards.", "s: Do I need to buy gift cards?")
    for i in range(2):
        output = LLMOutput.model_validate(
            {
                "flags": [
                    {
                        "flag": "untraceable_payment",
                        "message_id": f"m{i}",
                        "quote": case.messages[i].text,
                        "confidence": 0.9,
                    }
                ]
            }
        )
        assert not convert(output, case, set()).findings


def test_owner_fact_excludes_the_named_agent_and_invented_names() -> None:
    case = chat("a: The owner is Mira Vale; I am Rowan Pike, their managing agent.")
    output = LLMOutput.model_validate(
        {
            "facts": [
                {"key": "landlord_name", "value": value, "message_id": "m0"}
                for value in ("Mira Vale", "Rowan Pike", "Invented Person")
            ]
        }
    )
    assert [f.value for f in convert(output, case, set()).facts] == ["Mira Vale"]


@pytest.mark.parametrize(
    "text",
    [
        "Rowan Pike is the landlord's agent.",
        "I am not the owner Rowan Pike.",
        "I am Rowan Pike, the managing agent.",
    ],
)
def test_owner_role_must_be_affirmatively_stated(text: str) -> None:
    case = chat(f"a: {text}")
    output = LLMOutput.model_validate(
        {"facts": [{"key": "landlord_name", "value": "Rowan Pike", "message_id": "m0"}]}
    )
    assert not convert(output, case, set()).facts
