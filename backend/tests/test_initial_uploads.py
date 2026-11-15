"""Initial attachments stay retryable or skippable, even after interruption, while every round
grades the case live (there is no final decision for them to hold back)."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from app.contracts import (
    AgentReport,
    Case,
    Category,
    CheckId,
    DecisionMade,
    EvidenceKind,
    EvidenceRef,
    Finding,
    Landlord,
    Severity,
    StudentContext,
    Verdict,
)
from app.core.agent import AgentContext, BaseAgent, Need
from app.core.llm import FakeLLM
from app.intake import service as intake
from app.orchestrator.service import CaseService, Upload, UploadConflictError
from app.storage.repository import InitialUpload
from tests.conftest import EmptyAgent
from tests.test_email_pdf_uploads import scanned_pdf

MakeService = Callable[[list[BaseAgent] | None], CaseService]


def reservation(name: str, data: bytes, kind: EvidenceKind = EvidenceKind.EMAIL) -> InitialUpload:
    return InitialUpload(request_id=str(uuid4()), filename=name, kind=kind, size=len(data))


def upload(item: InitialUpload, data: bytes, *, retry: bool = False) -> Upload:
    return Upload(item.kind, data, item.filename, item.note, "Sam", item.request_id, retry)


async def test_a_failed_initial_file_stays_pending_while_the_case_is_graded(
    make_service: MakeService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intake, "UPLOADS_DIR", tmp_path / ".uploads")
    service = make_service(None)  # real orchestrator + default stub company hard flag
    good, bad = b"Viewing confirmed.", b"%PDF invalid"
    first, second = reservation("first.txt", good), reservation("broken.pdf", bad)
    case = await service.open_case(
        StudentContext(),
        landlord=Landlord(company_name="Example Ltd"),
        initial_uploads=[first, second],
    )
    await service.wait_idle()
    graded = await service.get_case(case.case_id)
    assert graded.status == "open" and graded.decision is not None  # assessed, not held

    await service.accept_evidence(case.case_id, upload(first, good))
    await service.wait_idle()
    failed = await service.accept_evidence(case.case_id, upload(second, bad))
    assert failed.read_error and failed.case.status == "open"
    manifest = await service.get_uploads(case.case_id)
    assert [u.state for u in manifest] == ["accepted", "pending"]
    assert manifest[1].read_error and manifest[1].evidence_id == failed.evidence_id

    await service.skip_upload(case.case_id, second.request_id)
    await service.wait_idle()
    final = await service.get_case(case.case_id)
    assert final.status == "open" and len(final.evidence) == 2
    assert [u.state for u in await service.get_uploads(case.case_id)] == ["accepted", "skipped"]
    # A lost skip response is idempotent.
    assert (await service.skip_upload(case.case_id, second.request_id))[1].state == "skipped"


async def test_pending_upload_survives_service_restart_and_reselection_finishes_it(
    make_service: MakeService,
) -> None:
    service = make_service([EmptyAgent()])
    data = b"Viewing confirmed Tuesday."
    item = reservation("email.txt", data)
    case = await service.open_case(StudentContext(), initial_uploads=[item])
    restarted = CaseService(service.repo, service.bus, service.agents, service.ctx, service.weights)
    assert (await restarted.get_uploads(case.case_id))[0].state == "pending"
    assert (await restarted.decide(case.case_id)).status == "open"  # an assessment, no lock
    await restarted.accept_evidence(case.case_id, upload(item, data))
    await restarted.wait_idle()
    assert (await restarted.get_uploads(case.case_id))[0].state == "accepted"
    assert len((await restarted.get_case(case.case_id)).evidence) == 1


async def test_ocr_retry_replaces_failed_read_without_duplicate_evidence_or_messages(
    make_service: MakeService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intake, "UPLOADS_DIR", tmp_path / ".uploads")
    service = make_service([EmptyAgent()])
    data = scanned_pdf()
    item = reservation("scan.pdf", data)
    case = await service.open_case(StudentContext(), initial_uploads=[item])
    first = await service.accept_evidence(case.case_id, upload(item, data))
    assert first.read_error and (await service.get_uploads(case.case_id))[0].state == "pending"
    service.ctx = replace(
        service.ctx,
        llm=FakeLLM(default='{"is_document": true, "text": "Viewing confirmed Tuesday."}'),
    )
    retried = await service.accept_evidence(case.case_id, upload(item, data, retry=True))
    await service.wait_idle()
    assert retried.read_error is None and retried.evidence_id == first.evidence_id
    assert len(retried.case.evidence) == len(retried.case.messages) == 1
    assert (await service.get_uploads(case.case_id))[0].state == "accepted"


async def test_wrong_reselected_file_does_not_release_hold(make_service: MakeService) -> None:
    service = make_service([EmptyAgent()])
    item = reservation("email.txt", b"Original email")
    case = await service.open_case(StudentContext(), initial_uploads=[item])
    with pytest.raises(UploadConflictError, match="does not match"):
        await service.accept_evidence(case.case_id, upload(item, b"Wrong size"))
    assert (await service.get_uploads(case.case_id))[0].state == "pending"
    assert not (await service.get_case(case.case_id)).evidence


class ChangingAgent(BaseAgent):
    name = "changing"
    requires = frozenset({Need.MESSAGES})

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.runs = 0

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        self.runs += 1
        if self.runs == 1:
            self.started.set()
            await self.release.wait()
        findings = []
        if len(case.messages) == 1:
            message = case.messages[0]
            findings = [
                Finding(
                    id="changing:identity",
                    agent=self.name,
                    check_id=CheckId.LANDLORD_IDENTITY,
                    title="Identity concern",
                    detail="Needs the second attachment.",
                    category=Category.IDENTITY,
                    severity=Severity.CRITICAL,
                    confidence=1,
                    hard_flag=True,
                    evidence=[EvidenceRef(evidence_id=message.evidence_id, quote=message.text)],
                )
            ]
        return self.report(case, findings=findings)


async def test_an_upload_during_a_round_is_graded_by_a_fresh_round(
    make_service: MakeService,
) -> None:
    agent = ChangingAgent()
    service = make_service([agent])
    first, second = reservation("first.txt", b"First"), reservation("second.txt", b"Second")
    case = await service.open_case(StudentContext(), initial_uploads=[first, second])
    events = service.bus.subscribe(case.case_id)
    await service.accept_evidence(case.case_id, upload(first, b"First"))
    await asyncio.wait_for(agent.started.wait(), 2)
    await service.accept_evidence(case.case_id, upload(second, b"Second"))
    agent.release.set()
    await service.wait_idle()
    final = await service.get_case(case.case_id)
    assert agent.runs == 2 and final.reports[agent.name].findings == []
    assert final.decision is not None and final.decision.verdict != Verdict.LIKELY_SCAM
    assessments = []
    while not events.empty():
        event = events.get_nowait()
        if isinstance(event, DecisionMade):
            assessments.append(event.decision.verdict)
    # The first round saw one file (a hard flag); the second, on both, clears it.
    assert assessments[-1] != Verdict.LIKELY_SCAM
