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
from app.orchestrator.service import (
    VERDICT_STANDS_TEXT,
    CaseNotFoundError,
    CaseService,
    Upload,
)
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


async def test_hard_flag_closes_the_case_as_likely_scam(
    make_service: MakeService, fake_agency_case: Case, bus: EventBus
) -> None:
    service = make_service(None)
    case = await _open(service, fake_agency_case)
    queue = bus.subscribe(case.case_id)

    case = await add_evidence_and_settle(service, case.case_id, _chat_upload(fake_agency_case))

    assert len(case.messages) == 8
    assert case.status == "decided"
    assert case.decision is not None and case.decision.verdict == Verdict.LIKELY_SCAM
    assert "companies_house:company_not_found" in case.decision.finding_ids
    assert case.reports["contract_checker"].status == AgentStatus.SKIPPED
    assert case.reports["message_checker"].status == AgentStatus.OK
    assert "crosscheck" in case.reports

    types = [e.type for e in _drain(queue)]
    assert types.count("agent_started") == 3  # companies_house, message_checker, emotion_classifier
    assert "score_updated" in types and types[-1] == "decision_made"
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
    assert case.status == "decided"
    assert case.decision is not None and case.decision.verdict == Verdict.LIKELY_SCAM
    assert "crosscheck:address" in case.decision.finding_ids


async def test_a_decided_case_takes_more_work_and_decides_again(
    make_service: MakeService, fake_agency_case: Case
) -> None:
    service = make_service(None)
    case = await _open(service, fake_agency_case)
    case = await add_evidence_and_settle(service, case.case_id, _chat_upload(fake_agency_case))
    assert case.status == "decided"
    await service.add_evidence(
        case.case_id, Upload(EvidenceKind.EMAIL, b"Hello, the flat is still free.", "mail.txt")
    )
    await service.wait_idle()
    case = await reply_and_settle(service, case.case_id, "why is that?")
    # The hard flags are still in the reports, so the reopened case is decided again.
    assert case.status == "decided" and case.decision is not None
    assert case.decision.verdict == "likely_scam"
    assert len(case.evidence) == 2
    assert case.chat[-1].role == "orchestrator"


async def test_messages_after_a_verdict_are_not_answered_with_the_same_text(
    make_service: MakeService, fake_agency_case: Case
) -> None:
    """Each message to a decided case is answered, and the verdict is not repeated word for
    word (before: the same verdict summary came back for every message)."""
    service = make_service(None)
    case = await _open(service, fake_agency_case)
    case = await add_evidence_and_settle(service, case.case_id, _chat_upload(fake_agency_case))
    case = await reply_and_settle(service, case.case_id, "why is this still suspicious")
    first = case.chat[-1].text
    assert case.decision is not None and case.decision.summary in first
    case = await reply_and_settle(service, case.case_id, "is this working")
    second = case.chat[-1].text
    assert case.status == "decided" and case.chat[-1].role == "orchestrator"
    assert case.decision is not None
    assert VERDICT_STANDS_TEXT in second
    assert case.decision.summary not in second and second != first


async def test_unknown_case(make_service: MakeService) -> None:
    with pytest.raises(CaseNotFoundError):
        await make_service(None).get_case("case_nope")
