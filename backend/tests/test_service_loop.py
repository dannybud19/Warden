"""Agents with empty reports: the consultant drives the loop to a decision."""

from collections.abc import Callable

import pytest

from app.contracts import ActionStatus, Case, CheckState, EvidenceKind, Verdict
from app.orchestrator.conversation import InvalidActionError
from app.orchestrator.events import EventBus
from app.orchestrator.service import CaseService, Upload
from tests.conftest import EmptyAgent, add_evidence_and_settle, reply_and_settle

MakeService = Callable[[list | None], CaseService]


def _oldest_open(case: Case) -> str:
    """The card the student answers next. Free text with several open actions is not guessed
    (decision 11), so these loops target an action the way the web app does."""
    return next(a.id for a in case.actions if a.status == ActionStatus.OPEN)


async def test_actions_proposed_replies_then_decision(
    make_service: MakeService, fake_agency_case: Case, bus: EventBus
) -> None:
    service = make_service([EmptyAgent()])
    opened = await service.open_case(
        fake_agency_case.student, fake_agency_case.listing, fake_agency_case.landlord
    )
    queue = bus.subscribe(opened.case_id)

    case = await add_evidence_and_settle(
        service, opened.case_id, Upload(EvidenceKind.EMAIL, b"Hello, the flat is available.")
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
        case = await reply_and_settle(
            service, case.case_id, "yes, they did", action_id=_oldest_open(case)
        )
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
    case = await add_evidence_and_settle(
        service, case.case_id, Upload(EvidenceKind.EMAIL, b"Hello")
    )
    case = await reply_and_settle(
        service,
        case.case_id,
        "No, they refused and said they are abroad",
        action_id="act_viewing",
    )
    viewing = next(c for c in case.checks if c.id.value == "in_person_viewing")
    assert viewing.state == CheckState.SUSPICIOUS
    assert case.score_history[-1].score == 100.0  # score only drops through clears


async def test_reply_with_no_open_actions_still_settles(
    make_service: MakeService, fake_agency_case: Case
) -> None:
    service = make_service([EmptyAgent()])
    case = await service.open_case(fake_agency_case.student, None, None)
    case = await add_evidence_and_settle(
        service, case.case_id, Upload(EvidenceKind.EMAIL, b"Hello")
    )
    for _ in range(4):
        case = await reply_and_settle(
            service, case.case_id, "unclear answer", action_id=_oldest_open(case)
        )
    assert case.status == "decided"
    assert all(a.outcome == "neutral" for a in case.actions)


async def _case_with_three_open_actions(make_service: MakeService, fake_agency_case: Case):
    service = make_service([EmptyAgent()])
    case = await service.open_case(fake_agency_case.student, None, None)
    case = await add_evidence_and_settle(
        service, case.case_id, Upload(EvidenceKind.EMAIL, b"Hello")
    )
    assert [a.id for a in case.actions] == [
        "act_viewing",
        "act_company_number",
        "act_payment_method",
    ]
    return service, case


async def test_reply_with_action_id_updates_only_that_action(
    make_service: MakeService, fake_agency_case: Case
) -> None:
    service, case = await _case_with_three_open_actions(make_service, fake_agency_case)
    before = {a.id: a.model_dump() for a in case.actions}
    # The second card, so the free-chat fallback (oldest open = act_viewing) would be caught.
    case = await reply_and_settle(
        service, case.case_id, "yes, registered", action_id="act_company_number"
    )
    by_id = {a.id: a for a in case.actions}
    assert by_id["act_company_number"].status == ActionStatus.DONE
    assert by_id["act_company_number"].outcome == "clears"
    assert by_id["act_company_number"].answer == "yes, registered"
    for other in ("act_viewing", "act_payment_method"):
        assert by_id[other].model_dump() == before[other]  # untouched in every field


async def test_skipped_sets_status_with_neutral_outcome(
    make_service: MakeService, fake_agency_case: Case
) -> None:
    service, case = await _case_with_three_open_actions(make_service, fake_agency_case)
    case = await reply_and_settle(
        service, case.case_id, "no, they refused", action_id="act_payment_method", status="skipped"
    )
    by_id = {a.id: a for a in case.actions}
    assert by_id["act_payment_method"].status == ActionStatus.SKIPPED
    assert by_id["act_payment_method"].outcome == "neutral"  # no keyword parsing
    assert by_id["act_viewing"].status == ActionStatus.OPEN


async def test_impossible_sets_status_with_neutral_outcome(
    make_service: MakeService, fake_agency_case: Case
) -> None:
    service, case = await _case_with_three_open_actions(make_service, fake_agency_case)
    case = await reply_and_settle(
        service, case.case_id, "", action_id="act_viewing", status="impossible"
    )
    by_id = {a.id: a for a in case.actions}
    assert by_id["act_viewing"].status == ActionStatus.IMPOSSIBLE
    assert by_id["act_viewing"].outcome == "neutral"


async def test_unknown_or_closed_action_id_is_rejected_without_changes(
    make_service: MakeService, fake_agency_case: Case
) -> None:
    service, case = await _case_with_three_open_actions(make_service, fake_agency_case)
    snapshot = (await service.get_case(case.case_id)).model_dump()
    with pytest.raises(InvalidActionError):
        await reply_and_settle(service, case.case_id, "yes", action_id="act_nope")
    assert (await service.get_case(case.case_id)).model_dump() == snapshot

    case = await reply_and_settle(service, case.case_id, "yes", action_id="act_viewing")
    snapshot = (await service.get_case(case.case_id)).model_dump()
    with pytest.raises(InvalidActionError):
        await reply_and_settle(service, case.case_id, "no", action_id="act_viewing")  # already done
    stored = await service.get_case(case.case_id)
    assert stored.model_dump() == snapshot
    by_id = {a.id: a.status for a in stored.actions}
    assert by_id["act_viewing"] == ActionStatus.DONE
    assert by_id["act_company_number"] == ActionStatus.OPEN
    assert by_id["act_payment_method"] == ActionStatus.OPEN
