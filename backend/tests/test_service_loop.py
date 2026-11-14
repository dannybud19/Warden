"""Agents with empty reports: the consultant drives the loop to a decision."""

from collections.abc import Callable

from app.contracts import ActionStatus, Case, CheckState, EvidenceKind, Verdict
from app.orchestrator.events import EventBus
from app.orchestrator.service import CaseService, Upload
from tests.conftest import EmptyAgent

MakeService = Callable[[list | None], CaseService]


async def test_actions_proposed_replies_then_decision(
    make_service: MakeService, fake_agency_case: Case, bus: EventBus
) -> None:
    service = make_service([EmptyAgent()])
    opened = await service.open_case(
        fake_agency_case.student, fake_agency_case.listing, fake_agency_case.landlord
    )
    queue = bus.subscribe(opened.case_id)

    case = await service.add_evidence(
        opened.case_id, Upload(EvidenceKind.EMAIL, b"Hello, the flat is available.")
    )
    assert case.status == "open"
    assert [a.id for a in case.actions] == [
        "act_viewing",
        "act_company_number",
        "act_payment_method",
    ]
    assert all(a.asked_at is not None for a in case.actions)
    assert case.score_history[-1].score == 100.0

    scores = [100.0]
    for _ in range(4):
        assert case.status == "open"
        case = await service.reply(case.case_id, "yes, they did")
        scores.append(case.score_history[-1].score)

    assert [a.id for a in case.actions][-1] == "act_deposit_scheme"
    assert all(a.status == ActionStatus.DONE for a in case.actions)
    assert case.status == "decided"
    assert case.decision is not None and case.decision.verdict == Verdict.NOT_VERIFIED
    assert scores == sorted(scores, reverse=True) and scores[-1] == 58.0
    states = {c.id.value: c.state for c in case.checks}
    assert states["right_to_let"] == CheckState.UNVERIFIED
    assert states["payment_safety"] == CheckState.CLEARED

    types = []
    while not queue.empty():
        types.append(queue.get_nowait().type)
    assert types.count("actions_proposed") == 2 and types[-1] == "decision_made"
    assert "orchestrator_message" in types


async def test_a_flagging_reply_makes_the_check_suspicious(
    make_service: MakeService, fake_agency_case: Case
) -> None:
    service = make_service([EmptyAgent()])
    case = await service.open_case(fake_agency_case.student, None, None)
    case = await service.add_evidence(case.case_id, Upload(EvidenceKind.EMAIL, b"Hello"))
    case = await service.reply(case.case_id, "No, they refused and said they are abroad")
    viewing = next(c for c in case.checks if c.id.value == "in_person_viewing")
    assert viewing.state == CheckState.SUSPICIOUS
    assert case.score_history[-1].score == 100.0  # score only drops through clears


async def test_reply_with_no_open_actions_still_settles(
    make_service: MakeService, fake_agency_case: Case
) -> None:
    service = make_service([EmptyAgent()])
    case = await service.open_case(fake_agency_case.student, None, None)
    case = await service.add_evidence(case.case_id, Upload(EvidenceKind.EMAIL, b"Hello"))
    for _ in range(4):
        case = await service.reply(case.case_id, "unclear answer")
    assert case.status == "decided"
    assert all(a.outcome == "neutral" for a in case.actions)
