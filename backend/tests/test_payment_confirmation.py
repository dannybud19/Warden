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
from app.core.agent import AgentContext, BaseAgent
from app.orchestrator import payment_confirmation
from app.orchestrator.checks import initial_checks
from app.orchestrator.conversation import parse
from app.orchestrator.service import CaseService
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
async def test_non_confirmation_preserves_concern_and_asks_for_clarification(
    make_service: MakeService, answer: str
) -> None:
    service, case = await payment_case(make_service)
    action = case.actions[0]
    case = await reply_and_settle(service, case.case_id, answer, action_id=action.id)
    assert case.status == "open" and case.decision is None
    old = next(a for a in case.actions if a.id == action.id)
    assert old.answer == answer and old.outcome == "neutral"
    assert any(a.status == ActionStatus.OPEN and "unresolved" in a.text for a in case.actions)
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
    assert any(a.status == ActionStatus.OPEN for a in case.actions)


async def test_direct_decide_cannot_bypass_confirmation(make_service: MakeService) -> None:
    service, case = await payment_case(make_service)
    case = await service.decide(case.case_id)
    assert case.status == "open" and case.decision is None
    assert len(case.actions) == 1


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


async def test_confirmation_is_bound_to_the_quoted_evidence(make_service: MakeService) -> None:
    _, case = await payment_case(make_service)
    original = payment_confirmation.payment_flags(case)[0]
    case.actions = parse(case, "yes", [], action_id=case.actions[0].id)
    assert payment_confirmation.confirmed(case, original)
    changed = original.model_copy(
        update={"evidence": [EvidenceRef(evidence_id="ev_other", quote="New demand")]}
    )
    assert not payment_confirmation.confirmed(case, changed)


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
