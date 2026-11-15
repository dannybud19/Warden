"""All stubs on fake_agency: the hard flags close the case as likely_scam."""

from collections.abc import Callable

import pytest

from app.contracts import (
    AgentStatus,
    Case,
    CheckState,
    EvidenceKind,
    StreamEvent,
    Verdict,
)
from app.orchestrator.checks import initial_checks
from app.orchestrator.events import EventBus
from app.orchestrator.service import CaseNotFoundError, CaseService, Upload
from tests.conftest import add_evidence_and_settle, reply_and_settle

MakeService = Callable[[list | None], CaseService]


async def _open(service: CaseService, case: Case) -> Case:
    """Open without a company name or number, so nothing is analysed until the first upload
    (opening with one starts the agency check at once: see test_service_background.py)."""
    landlord = case.landlord
    if landlord:
        landlord = landlord.model_copy(update={"company_name": None, "company_number": None})
    return await service.open_case(case.student, case.listing, landlord)


def _chat_upload(case: Case) -> Upload:
    chat = next(e for e in case.evidence if e.kind == EvidenceKind.CHAT_EXPORT)
    return Upload(
        EvidenceKind.CHAT_EXPORT, (chat.extracted_text or "").encode(), student_name="Sam"
    )


def _drain(queue) -> list[StreamEvent]:
    events: list[StreamEvent] = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


async def test_open_case_starts_at_100_with_all_checks_unverified(
    make_service: MakeService, fake_agency_case: Case
) -> None:
    case = await _open(make_service(None), fake_agency_case)
    assert case.status == "open"
    assert len(case.checks) == 8
    assert all(c.state == CheckState.UNVERIFIED for c in case.checks)
    assert [s.score for s in case.score_history] == [100.0]


async def test_hard_flag_assesses_likely_scam_and_keeps_the_case_open(
    make_service: MakeService, fake_agency_case: Case, bus: EventBus
) -> None:
    service = make_service(None)
    case = await _open(service, fake_agency_case)
    queue = bus.subscribe(case.case_id)

    case = await add_evidence_and_settle(service, case.case_id, _chat_upload(fake_agency_case))

    assert len(case.messages) == 8
    assert case.status == "open"
    assert case.decision is not None and case.decision.verdict == Verdict.LIKELY_SCAM
    assert "companies_house:company_not_found" in case.decision.finding_ids
    assert case.reports["contract_checker"].status == AgentStatus.SKIPPED
    assert case.reports["message_checker"].status == AgentStatus.OK
    assert "crosscheck" in case.reports

    types = [e.type for e in _drain(queue)]
    assert types.count("agent_started") == 3  # companies_house, message_checker, emotion_classifier
    assert "score_updated" in types and "decision_made" in types
    assert types.index("decision_made") == types.index("score_updated") + 1
    stored = await service.get_case(case.case_id)
    assert stored.decision == case.decision


async def test_contract_address_mismatch_is_a_crosscheck_hard_flag(
    make_service: MakeService, fake_agency_case: Case
) -> None:
    """Seeded with the fixture case so the stub reports' evidence ids (ev_contract) match."""
    service = make_service(None)
    seeded = fake_agency_case.model_copy(update={"checks": initial_checks()})
    await service.repo.create(seeded)
    case = await service.analyse(seeded.case_id)
    cross = case.reports["crosscheck"].findings
    assert [(f.id, f.hard_flag) for f in cross] == [("crosscheck:address", True)]
    assert case.reports["contract_checker"].status == AgentStatus.OK
    assert case.status == "open"
    assert case.decision is not None and case.decision.verdict == Verdict.LIKELY_SCAM
    assert "crosscheck:address" in case.decision.finding_ids


async def test_a_likely_scam_case_still_takes_more_work(
    make_service: MakeService, fake_agency_case: Case
) -> None:
    """A hard flag used to close the case (409 from then on); now every input regrades it."""
    service = make_service(None)
    case = await _open(service, fake_agency_case)
    case = await add_evidence_and_settle(service, case.case_id, _chat_upload(fake_agency_case))
    assert case.decision is not None and case.decision.verdict == Verdict.LIKELY_SCAM
    rounds = len(case.score_history)

    case = await add_evidence_and_settle(service, case.case_id, _chat_upload(fake_agency_case))
    assert len(case.score_history) == rounds + 1
    case = await reply_and_settle(service, case.case_id, "yes")
    assert len(case.score_history) == rounds + 2
    assert case.status == "open" and case.chat[-1].role == "orchestrator"


async def test_unknown_case(make_service: MakeService) -> None:
    with pytest.raises(CaseNotFoundError):
        await make_service(None).get_case("case_nope")
