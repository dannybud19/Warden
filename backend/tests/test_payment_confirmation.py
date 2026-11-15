"""Payment concerns are confirmed through the real service/reply loop before a verdict."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from app.agents.message_checker.agent import MessageCheckerAgent
from app.contracts import (
    Action,
    ActionKind,
    ActionStatus,
    AgentReport,
    Case,
    Category,
    CheckId,
    CheckState,
    Evidence,
    EvidenceKind,
    EvidenceRef,
    Finding,
    Message,
    Severity,
    Verdict,
)
from app.core.agent import AgentContext, BaseAgent, Need
from app.orchestrator import payment_confirmation
from app.orchestrator.checks import initial_checks
from app.orchestrator.conversation import _target, parse  # pyright: ignore[reportPrivateUsage]
from app.orchestrator.service import CONFIRM_PAYMENT_TEXT, CaseService
from tests.conftest import reply_and_settle

MakeService = Callable[[list[BaseAgent] | None], CaseService]


async def payment_case(
    make_service: MakeService, text: str = "Pay the deposit before any viewing."
):
    service = make_service([MessageCheckerAgent()])
    now = datetime(2026, 11, 14, tzinfo=UTC)
    case = Case(
        case_id="payment",
        created_at=now,
        checks=initial_checks(),
        evidence=[
            Evidence(
                id="ev_pay", kind=EvidenceKind.CHAT_EXPORT, uploaded_at=now, extracted_text=text
            )
        ],
        messages=[
            Message(
                id="msg_pay", evidence_id="ev_pay", sender="agent", channel="whatsapp", text=text
            )
        ],
    )
    await service.repo.create(case)
    return service, await service.analyse(case.case_id)


@pytest.mark.parametrize(
    "text",
    [
        "Pay the deposit before any viewing.",
        "Buy gift cards and send me the codes.",
        "Pay the deposit in Bitcoin.",
    ],
)
async def test_payment_waits_for_targeted_confirmation(
    make_service: MakeService, text: str
) -> None:
    service, case = await payment_case(make_service, text)
    assert case.status == "open" and case.decision is None
    action = next(a for a in case.actions if a.id.startswith(payment_confirmation.PREFIX))
    assert action.asked_at and text in action.text
    assert (
        next(c for c in case.checks if c.id == CheckId.PAYMENT_SAFETY).state
        == CheckState.SUSPICIOUS
    )
    case = await reply_and_settle(service, case.case_id, "yes", action_id=action.id)
    assert case.decision and case.decision.verdict == Verdict.LIKELY_SCAM


@pytest.mark.parametrize("answer", ["no", "unsure", "yes, but only after viewing", "confirmed", ""])
async def test_non_confirmation_preserves_concern_without_asking_again(
    make_service: MakeService, answer: str
) -> None:
    service, case = await payment_case(make_service)
    action = case.actions[0]
    case = await reply_and_settle(service, case.case_id, answer, action_id=action.id)
    assert case.status == "open" and case.decision is None
    old = next(a for a in case.actions if a.id == action.id)
    assert old.answer == answer and old.outcome == "neutral"
    # Answered once: the conversation moves on instead of repeating the same question.
    confirmations = [a for a in case.actions if a.id.startswith(payment_confirmation.PREFIX)]
    assert confirmations == [old]
    assert payment_confirmation.pending(case) and not payment_confirmation.awaiting(case)
    assert case.chat[-1].text != CONFIRM_PAYMENT_TEXT
    assert (
        next(c for c in case.checks if c.id == CheckId.PAYMENT_SAFETY).state
        == CheckState.SUSPICIOUS
    )


@pytest.mark.parametrize("status", ["skipped", "impossible"])
async def test_skipping_cannot_confirm_or_clear_payment(
    make_service: MakeService, status: str
) -> None:
    service, case = await payment_case(make_service)
    case = await reply_and_settle(
        service, case.case_id, "yes", action_id=case.actions[0].id, status=status
    )
    assert case.decision is None
    assert case.actions[0].outcome == "neutral"
    assert payment_confirmation.pending(case)  # skipping keeps the concern; it is not asked again


async def test_direct_decide_cannot_bypass_confirmation(make_service: MakeService) -> None:
    service, case = await payment_case(make_service)
    case = await service.decide(case.case_id)
    assert case.status == "open" and case.decision is None
    assert len(case.actions) == 1


async def test_payment_confirmation_is_asked_even_when_three_steps_are_open(
    make_service: MakeService,
) -> None:
    """The agency check opens three steps when a home is added. Waiting for room then left the
    concern unasked while it blocked every other step, and the chat went silent."""
    service, case = await payment_case(make_service)
    case.actions = [
        Action(
            id=f"old_{check_id}",
            check_id=check_id,
            kind=ActionKind.QUESTION,
            text="Can you provide more evidence for this check?",
        )
        for check_id in (
            CheckId.LANDLORD_IDENTITY,
            CheckId.RIGHT_TO_LET,
            CheckId.IN_PERSON_VIEWING,
        )
    ]
    await service.repo.save(case)
    case = await service.analyse(case.case_id)
    open_actions = [a for a in case.actions if a.status == ActionStatus.OPEN]
    confirmations = [a for a in open_actions if a.id.startswith(payment_confirmation.PREFIX)]
    assert case.decision is None and len(open_actions) == 4
    assert len(confirmations) == 1
    assert "Pay the deposit before any viewing." in confirmations[0].text


async def test_a_statement_gets_a_reply_while_a_confirmation_is_open(
    make_service: MakeService,
) -> None:
    """Not a question and not an answer to the confirmation: the student must still hear back."""
    service, case = await payment_case(make_service)
    said = len([t for t in case.chat if t.role == "orchestrator"])
    case = await reply_and_settle(
        service, case.case_id, "I just checked with the agent, it was a typo in the contract"
    )
    assert case.chat[-1].role == "orchestrator"
    assert len([t for t in case.chat if t.role == "orchestrator"]) == said + 1
    assert any(a.status == ActionStatus.OPEN for a in case.actions)  # still to be confirmed


async def test_free_chat_prioritises_payment_confirmation_over_old_questions(
    make_service: MakeService,
) -> None:
    _, case = await payment_case(make_service)
    case.actions.insert(
        0,
        Action(
            id="old",
            check_id=CheckId.LANDLORD_IDENTITY,
            kind=ActionKind.QUESTION,
            text="Did they give you ID?",
        ),
    )
    actions = parse(case, "yes", [])
    assert actions[0].status == ActionStatus.OPEN
    assert actions[1].outcome == "flags"


async def test_confirmation_carries_over_when_the_evidence_grows(
    make_service: MakeService,
) -> None:
    _, case = await payment_case(make_service)
    original = payment_confirmation.payment_flags(case)[0]
    case.actions = parse(case, "yes", [], action_id=case.actions[0].id)
    assert payment_confirmation.confirmed(case, original)
    grown = original.model_copy(
        update={"evidence": [EvidenceRef(evidence_id="ev_other", quote="New demand")]}
    )
    assert payment_confirmation.confirmed(case, grown)  # same finding, more evidence
    other = grown.model_copy(update={"id": "message_checker:untraceable_payment"})
    assert not payment_confirmation.confirmed(case, other)  # a different finding is not


class GrowingPayment(BaseAgent):
    """A payment hard flag whose id is fixed but whose quotes grow with every message."""

    name = "growing_payment"
    requires = frozenset({Need.MESSAGES})
    finding_id = "growing_payment:payment_before_viewing"

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        if not case.messages:
            return self.report(case)
        return self.report(
            case,
            findings=[
                Finding(
                    id=self.finding_id,
                    agent=self.name,
                    check_id=CheckId.PAYMENT_SAFETY,
                    title="Payment before viewing",
                    detail="They want money first",
                    category=Category.PAYMENT,
                    severity=Severity.CRITICAL,
                    confidence=0.95,
                    hard_flag=True,
                    evidence=[
                        EvidenceRef(evidence_id=m.evidence_id, quote=m.text) for m in case.messages
                    ],
                )
            ],
        )


async def add_message(service: CaseService, case_id: str, text: str) -> Case:
    """A further part of the chat arrives: same evidence upload, one more message."""
    case = await service.repo.get(case_id)
    assert case
    n = len(case.messages) + 1
    case.messages.append(
        Message(id=f"msg_{n}", evidence_id=f"ev_{n}", sender="agent", channel="whatsapp", text=text)
    )
    await service.repo.save(case)
    return await service.analyse(case_id)


def confirmations(case: Case) -> list[Action]:
    return [a for a in case.actions if a.id.startswith(payment_confirmation.PREFIX)]


def orchestrator_says(case: Case, text: str) -> int:
    return sum(t.role == "orchestrator" and t.text == text for t in case.chat)


async def growing_case(make_service: MakeService) -> tuple[CaseService, Case]:
    service = make_service([GrowingPayment()])
    now = datetime(2026, 11, 14, tzinfo=UTC)
    case = Case(case_id="grow", created_at=now, checks=initial_checks())
    await service.repo.create(case)
    return service, await add_message(service, "grow", "Pay the deposit before any viewing.")


async def test_evidence_growing_keeps_one_open_confirmation(make_service: MakeService) -> None:
    service, case = await growing_case(make_service)
    first = confirmations(case)
    assert len(first) == 1 and orchestrator_says(case, CONFIRM_PAYMENT_TEXT) == 1
    for extra in ("Send it today or I give the flat away.", "Transfer to my personal account."):
        case = await add_message(service, case.case_id, extra)
    [only] = confirmations(case)
    assert only.id == first[0].id and only.status == ActionStatus.OPEN
    assert "Transfer to my personal account." in only.text  # the card shows the current quotes
    assert "Pay the deposit before any viewing." in only.text
    assert orchestrator_says(case, CONFIRM_PAYMENT_TEXT) == 1  # not posted a second time
    assert case.decision is None and len(payment_confirmation.awaiting(case)) == 1


async def test_yes_still_confirms_after_the_evidence_grows(make_service: MakeService) -> None:
    service, case = await growing_case(make_service)
    case = await add_message(service, case.case_id, "Send it today or I give the flat away.")
    [card] = confirmations(case)
    case = await reply_and_settle(service, case.case_id, "yes", action_id=card.id)
    assert case.decision and case.decision.verdict == Verdict.LIKELY_SCAM
    flag = payment_confirmation.payment_flags(case)[0]
    assert payment_confirmation.confirmed(case, flag)
    # More quotes for the same finding after the answer: still confirmed, nothing asked again.
    grown = flag.model_copy(
        update={"evidence": [*flag.evidence, EvidenceRef(evidence_id="ev_9", quote="Last chance")]}
    )
    assert payment_confirmation.confirmed(case, grown)
    assert not payment_confirmation.awaiting(case)


async def test_no_is_not_asked_again_when_the_evidence_grows(make_service: MakeService) -> None:
    service, case = await growing_case(make_service)
    [card] = confirmations(case)
    case = await reply_and_settle(service, case.case_id, "no", action_id=card.id)
    assert case.decision is None and not payment_confirmation.awaiting(case)
    said = orchestrator_says(case, CONFIRM_PAYMENT_TEXT)
    case = await add_message(service, case.case_id, "Send it today or I give the flat away.")
    assert [a.id for a in confirmations(case)] == [card.id]
    assert confirmations(case)[0].status == ActionStatus.DONE
    assert orchestrator_says(case, CONFIRM_PAYMENT_TEXT) == said
    assert payment_confirmation.pending(case) and not payment_confirmation.awaiting(case)
    assert case.decision is None  # kept pending, never cleared, cannot close the case


async def test_a_different_finding_is_still_asked(make_service: MakeService) -> None:
    service, case = await growing_case(make_service)
    [card] = confirmations(case)
    case = await reply_and_settle(service, case.case_id, "no", action_id=card.id)
    service.agents.append(CompanyPaymentFlag())
    case = await add_message(service, case.case_id, "Pay in gift cards.")
    ids = [a.id for a in confirmations(case)]
    assert len(ids) == 2 and card.id in ids
    new = next(a for a in confirmations(case) if a.id != card.id)
    assert new.status == ActionStatus.OPEN and "gift cards" in new.text


class CompanyPaymentFlag(GrowingPayment):
    """Another payment concern: a different finding id, so a separate confirmation."""

    name = "other_payment"
    finding_id = "other_payment:untraceable_payment"


class CompanyHardFlag(BaseAgent):
    name = "company_test"

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        return self.report(
            case,
            findings=[
                Finding(
                    id="company_test:dissolved",
                    agent=self.name,
                    check_id=CheckId.LANDLORD_IDENTITY,
                    title="Dissolved",
                    detail="Register record",
                    category=Category.IDENTITY,
                    severity=Severity.CRITICAL,
                    confidence=0.95,
                    hard_flag=True,
                    evidence=[EvidenceRef(evidence_id="register", quote="dissolved")],
                )
            ],
        )


async def test_unrelated_hard_flag_still_decides_immediately(make_service: MakeService) -> None:
    service, case = await payment_case(make_service)
    service.agents.append(CompanyHardFlag())
    case = await service.analyse(case.case_id)
    assert case.decision and case.decision.verdict == Verdict.LIKELY_SCAM
    assert "company_test:dissolved" in case.decision.finding_ids


async def test_long_reply_is_read_against_every_open_action(make_service: MakeService) -> None:
    _, case = await payment_case(make_service)
    case.actions.append(
        Action(
            id="view",
            check_id=CheckId.IN_PERSON_VIEWING,
            kind=ActionKind.ACTION,
            text="Book an in-person viewing.",
        )
    )
    long_reply = "they no longer want the money before the viewing and we booked one"
    assert _target(case, None, long_reply) is None  # every open action, not only the confirmation
    confirmation = case.actions[0].id
    assert _target(case, None, "no") == confirmation
    assert _target(case, None, "not sure") == confirmation
