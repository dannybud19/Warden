"""A home never closes: every input runs a full round and regrades the live assessment.

Each upload, reply and call runs intake, the agents whose inputs changed, the Cross-checker,
`checks.update`, the score and the assessment, then saves and streams `score_updated` plus
`decision_made` (the assessment). A hard flag, which used to close the case with a 409 from
then on, now only moves the assessment.
"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.contracts import (
    AgentReport,
    Case,
    Category,
    CheckId,
    CheckState,
    Decision,
    DecisionMade,
    EvidenceKind,
    EvidenceRef,
    Finding,
    ScoreUpdated,
    Severity,
    StudentContext,
    Verdict,
)
from app.core.agent import AgentContext, BaseAgent, Need
from app.orchestrator import debrief
from app.orchestrator.checks import initial_checks
from app.orchestrator.events import EventBus
from app.orchestrator.service import CaseService, Upload
from tests.conftest import add_evidence_and_settle, reply_and_settle

MakeService = Callable[[list[BaseAgent] | None], CaseService]

VIEWED = "We viewed the flat in person on Monday."
DISSOLVED = "Our company was dissolved last year but we still let flats."


def _finding(case: Case, phrase: str, **fields: Any) -> Finding | None:
    """A finding quoting the first message that contains `phrase`, if any."""
    message = next((m for m in case.messages if phrase in m.text), None)
    if message is None:
        return None
    return Finding(
        agent="reader",
        title=fields.pop("title"),
        detail="Read from the student's upload.",
        category=Category.IDENTITY,
        severity=Severity.HIGH,
        confidence=0.9,
        evidence=[EvidenceRef(evidence_id=message.evidence_id, quote=phrase)],
        **fields,
    )


class ReaderAgent(BaseAgent):
    """Clears the viewing once a message says it happened; a dissolved company is a hard flag."""

    name = "reader"
    requires = frozenset({Need.MESSAGES})

    def __init__(self) -> None:
        self.runs = 0

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        self.runs += 1
        found = [
            _finding(
                case,
                VIEWED,
                id="reader:viewed",
                title="The student viewed the flat in person",
                check_id=CheckId.IN_PERSON_VIEWING,
                supports="cleared",
            ),
            _finding(
                case,
                DISSOLVED,
                id="reader:dissolved",
                title="The company is dissolved",
                check_id=CheckId.LANDLORD_IDENTITY,
                hard_flag=True,
            ),
        ]
        return self.report(case, findings=[f for f in found if f])


def _drain(queue: Any) -> list[Any]:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


def _state(case: Case, check_id: CheckId) -> CheckState:
    return next(c.state for c in case.checks if c.id == check_id)


async def test_three_uploads_in_a_row_each_regrade_and_a_hard_flag_closes_nothing(
    make_service: MakeService, bus: EventBus
) -> None:
    reader = ReaderAgent()
    service = make_service([reader])
    case = await service.open_case(StudentContext())
    queue = bus.subscribe(case.case_id)
    assert len(case.score_history) == 1

    # 1. A neutral email: one round, assessed but nothing verified yet.
    case = await add_evidence_and_settle(
        service, case.case_id, Upload(EvidenceKind.EMAIL, b"Hello, the flat is available.")
    )
    assert len(case.score_history) == 2 and reader.runs == 1
    assert case.decision is not None and case.decision.verdict == Verdict.NOT_VERIFIED
    first_score = case.score_history[-1].score

    # 2. The viewing happened: the check clears, the score drops, the assessment is redone.
    first_assessment = case.decision
    case = await add_evidence_and_settle(
        service, case.case_id, Upload(EvidenceKind.EMAIL, VIEWED.encode())
    )
    assert len(case.score_history) == 3 and reader.runs == 2
    assert _state(case, CheckId.IN_PERSON_VIEWING) == CheckState.CLEARED
    assert case.score_history[-1].score < first_score
    assert case.decision is not None and case.decision.decided_at > first_assessment.decided_at

    # 3. A confirmed hard flag: this used to decide the case and lock it.
    case = await add_evidence_and_settle(
        service, case.case_id, Upload(EvidenceKind.EMAIL, DISSOLVED.encode())
    )
    assert len(case.score_history) == 4
    assert _state(case, CheckId.LANDLORD_IDENTITY) == CheckState.SUSPICIOUS
    assert case.decision is not None and case.decision.verdict == Verdict.LIKELY_SCAM
    assert case.status == "open"

    # Still accepted afterwards (no 409): another file, a chat reply and a call all regrade.
    case = await add_evidence_and_settle(
        service, case.case_id, Upload(EvidenceKind.DOCUMENT, b"A fourth file.")
    )
    assert len(case.score_history) == 5
    case = await reply_and_settle(service, case.case_id, "Is there anything else I can do?")
    assert len(case.score_history) == 6
    line = debrief.CallLine(
        "student", "They told me the deposit goes to a scheme.", datetime.now(UTC)
    )
    await service.debrief(case.case_id, debrief.CallDebrief(lines=(line,)))
    await service.wait_idle()
    case = await service.get_case(case.case_id)
    assert len(case.score_history) == 7 and case.status == "open"
    assert len(case.evidence) == 5  # four files and the call

    # Every round streamed its score and then its assessment, in that order.
    events = [e for e in _drain(queue) if isinstance(e, ScoreUpdated | DecisionMade)]
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["ScoreUpdated", "DecisionMade"] * 6
    verdicts = [e.decision.verdict for e in events if isinstance(e, DecisionMade)]
    assert verdicts[:3] == [Verdict.NOT_VERIFIED, Verdict.NOT_VERIFIED, Verdict.LIKELY_SCAM]


async def test_a_case_stored_as_decided_loads_open_and_takes_new_input(
    make_service: MakeService,
) -> None:
    """Cases saved by the old version (status "decided") must not stay locked."""
    service = make_service([ReaderAgent()])
    now = datetime.now(UTC)
    old = Case(
        case_id="case_old",
        created_at=now,
        status="decided",
        checks=initial_checks(),
        decision=Decision(
            verdict=Verdict.LIKELY_SCAM,
            decided_at=now,
            summary="Old final verdict.",
            reasons=[],
            finding_ids=[],
        ),
    )
    await service.repo.create(old)

    assert (await service.get_case("case_old")).status == "open"
    case = await add_evidence_and_settle(
        service, "case_old", Upload(EvidenceKind.EMAIL, b"Hello, the flat is available.")
    )
    assert case.status == "open" and len(case.evidence) == 1
    assert case.decision is not None and case.decision.verdict == Verdict.NOT_VERIFIED
    stored = await service.repo.get("case_old")
    assert stored is not None and stored.status == "open"  # migrated on the next save


class SlowReader(ReaderAgent):
    """Holds its first run until released, so input can arrive while a round is running."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        if self.runs == 0:
            self.started.set()
            await self.release.wait()
        return await super().run(case, ctx)


async def test_input_that_arrives_during_a_round_is_graded_by_the_next_round(
    make_service: MakeService,
) -> None:
    reader = SlowReader()
    service = make_service([reader])
    case = await service.open_case(StudentContext())
    await service.add_evidence(case.case_id, Upload(EvidenceKind.EMAIL, b"Hello there."))
    await asyncio.wait_for(reader.started.wait(), 2)

    # While the first round runs: another file and a chat reply.
    await service.add_evidence(case.case_id, Upload(EvidenceKind.EMAIL, VIEWED.encode()))
    await service.reply(case.case_id, "I went to see it on Monday.")
    reader.release.set()
    await service.wait_idle()

    case = await service.get_case(case.case_id)
    assert reader.runs == 2  # a second round read the file that arrived meanwhile
    assert _state(case, CheckId.IN_PERSON_VIEWING) == CheckState.CLEARED
    assert len(case.score_history) == 3  # open, then one round each
    assert any(t.role == "student" for t in case.chat)
    assert case.chat[-1].role == "orchestrator"  # the reply got an answer
