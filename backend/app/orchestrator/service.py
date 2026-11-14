"""CaseService: the use cases the API calls. Every state change is saved, then published."""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from app.aggregators.consultant.consultant import propose_actions
from app.aggregators.scoring.scoring import Weights, score
from app.contracts import (
    Action,
    ActionsProposed,
    ActionStatus,
    AgentReport,
    AgentStatus,
    Case,
    DecisionMade,
    EvidenceKind,
    Finding,
    Landlord,
    Listing,
    OrchestratorMessage,
    ScoreUpdated,
    StreamEvent,
    StudentContext,
)
from app.core.agent import AgentContext, BaseAgent
from app.core.ids import new_id
from app.intake.service import ingest
from app.orchestrator import checks as checks_mod
from app.orchestrator import conversation, crosscheck, decision
from app.orchestrator.events import EventBus
from app.orchestrator.runner import run_agents
from app.storage.repository import CaseRepository


class CaseNotFoundError(Exception):
    """No case with this id (HTTP 404)."""


class CaseClosedError(Exception):
    """The case is already decided (HTTP 409)."""


@dataclass(frozen=True)
class Upload:
    """One thing the student uploaded or pasted."""

    kind: EvidenceKind
    data: bytes
    filename: str | None = None
    note: str | None = None
    student_name: str | None = None


class CaseService:
    def __init__(
        self,
        repo: CaseRepository,
        bus: EventBus,
        agents: list[BaseAgent],
        ctx: AgentContext,
        weights: Weights,
    ) -> None:
        self.repo = repo
        self.bus = bus
        self.agents = agents
        self.ctx = ctx
        self.weights = weights
        # NOTE: one lock per case so overlapping requests cannot overwrite each other.
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def _load(self, case_id: str, *, must_be_open: bool = False) -> Case:
        case = await self.repo.get(case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        if must_be_open and case.status == "decided":
            raise CaseClosedError(case_id)
        return case

    async def _emit(self, case_id: str, event: StreamEvent) -> None:
        await self.bus.publish(case_id, event)

    async def get_case(self, case_id: str) -> Case:
        """The stored case, or CaseNotFoundError."""
        return await self._load(case_id)

    async def open_case(
        self,
        student: StudentContext,
        listing: Listing | None = None,
        landlord: Landlord | None = None,
    ) -> Case:
        """New case: all 8 checks UNVERIFIED and a first score of 100."""
        case = Case(
            case_id=new_id("case"),
            created_at=datetime.now(UTC),
            student=student,
            listing=listing,
            landlord=landlord,
            checks=checks_mod.initial_checks(),
        )
        first = score(case.checks, self.weights)
        case.score_history.append(first)
        await self.repo.create(case)
        await self._emit(case.case_id, ScoreUpdated(score=first))
        return case

    async def add_evidence(self, case_id: str, upload: Upload) -> Case:
        """Ingest an upload (text and messages), then analyse."""
        async with self._locks[case_id]:
            case = await self._load(case_id, must_be_open=True)
            case = await ingest(
                case,
                upload.kind,
                upload.filename,
                upload.data,
                upload.note,
                upload.student_name,
            )
            await self.repo.save(case)
            return await self._analyse(case)

    async def analyse(self, case_id: str) -> Case:
        """Run the agents, crosscheck, update checks and score, then ask or decide."""
        async with self._locks[case_id]:
            case = await self._load(case_id, must_be_open=True)
            return await self._analyse(case)

    async def reply(
        self,
        case_id: str,
        text: str,
        evidence_ids: list[str] | None = None,
        action_id: str | None = None,
        status: conversation.ReplyStatus | None = None,
    ) -> Case:
        """Apply the student's reply to the targeted (or oldest open) action, then analyse."""
        async with self._locks[case_id]:
            case = await self._load(case_id, must_be_open=True)
            case.actions = conversation.parse(case, text, evidence_ids or [], action_id, status)
            await self.repo.save(case)
            return await self._analyse(case)

    async def decide(self, case_id: str) -> Case:
        """Close the case with a final decision."""
        async with self._locks[case_id]:
            case = await self._load(case_id, must_be_open=True)
            return await self._decide(case)

    async def _decide(self, case: Case) -> Case:
        case.decision = decision.decide(case)
        case.status = "decided"
        await self.repo.save(case)
        await self._emit(case.case_id, DecisionMade(decision=case.decision))
        return case

    async def _analyse(self, case: Case) -> Case:
        async def publish(event: StreamEvent) -> None:
            await self._emit(case.case_id, event)

        new_reports = await run_agents(case, self.agents, self.ctx, publish)
        case.reports.update(new_reports)

        # NOTE: crosscheck findings are stored as a pseudo-report named "crosscheck" so that
        # `decision.decide` can see them (the Case has no other place for them).
        cross = crosscheck.compare(case, case.reports)
        case.reports["crosscheck"] = AgentReport(
            agent="crosscheck",
            version="0.1.0",
            status=AgentStatus.OK,
            input_hash="",
            findings=cross,
        )

        findings: list[Finding] = [f for r in case.reports.values() for f in r.findings]
        case.checks = checks_mod.update(case, findings)
        result = score(case.checks, self.weights)
        case.score_history.append(result)
        await self.repo.save(case)
        await self._emit(case.case_id, ScoreUpdated(score=result))

        if decision.hard_flags(case):
            return await self._decide(case)

        existing = {a.id for a in case.actions}
        proposals = await propose_actions(case, result, self.ctx)
        fresh = [a for a in proposals if a.id not in existing]
        if fresh:
            now = datetime.now(UTC)
            fresh = [a.model_copy(update={"asked_at": now}) for a in fresh]
            case.actions.extend(fresh)
            await self.repo.save(case)
            await self._emit(case.case_id, ActionsProposed(actions=fresh))
            await self._emit(
                case.case_id, OrchestratorMessage(text=_next_steps_message(result.score, fresh))
            )
        elif not any(a.status == ActionStatus.OPEN for a in case.actions):
            return await self._decide(case)
        return case


def _next_steps_message(current_score: float, new_actions: list[Action]) -> str:
    """Phase 0 template. TODO(Danny, WS A): LLM composer (max 60 words)."""
    count = len(new_actions)
    noun = "step" if count == 1 else "steps"
    return (
        f"Risk score is {current_score:.0f}/100. I suggest {count} next {noun}: answer them "
        "below, or skip any you cannot do."
    )
