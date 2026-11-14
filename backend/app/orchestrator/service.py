"""CaseService: the use cases the API calls. Every state change is saved, then published."""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from app.aggregators.consultant.consultant import propose_actions
from app.aggregators.listing_reader.reader import apply_details, read_listing, summary_message
from app.aggregators.scoring.scoring import Weights, score
from app.contracts import (
    Action,
    ActionsProposed,
    ActionStatus,
    AgentFinished,
    AgentReport,
    AgentStarted,
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
        # NOTE: two locks per case. `_locks` guards every read-modify-write of the stored case and
        # is only ever held briefly. `_analysis_locks` makes sure one analysis runs at a time; it is
        # held for the whole (slow) agent run, so uploads and replies are never blocked by it.
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._analysis_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # Background analyses: strong references (so they are not garbage collected), the cases that
        # have one waiting to start (a second request would find the same latest state, so skip it),
        # and the agents currently running per case (replayed to a client that connects late).
        self._tasks: set[asyncio.Task[None]] = set()
        self._queued: set[str] = set()
        self._running: defaultdict[str, set[str]] = defaultdict(set)

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
        """New case: all 8 checks UNVERIFIED and a first score of 100.

        A listing link is read first (`aggregators/listing_reader`): what the page states fills the
        listing and landlord fields the student left empty. It never raises, and in stub mode it
        makes no request.
        """
        note = None
        if listing and listing.url:
            details = await read_listing(listing.url, self.ctx)
            listing, landlord = apply_details(listing, landlord, details)
            note = summary_message(details)
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
        if note:
            await self._emit(case.case_id, OrchestratorMessage(text=note))
        landlord = case.landlord
        if landlord and (
            (landlord.company_name or "").strip() or (landlord.company_number or "").strip()
        ):
            # NOTE: the agency check starts now; its results arrive over the stream.
            self._schedule(case.case_id)
        return case

    async def add_evidence(self, case_id: str, upload: Upload) -> Case:
        """Ingest an upload (text and messages) and save it, then analyse in the background."""
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
        self._schedule(case_id)
        return case

    async def analyse(self, case_id: str) -> Case:
        """Run the agents, crosscheck, update checks and score, then ask or decide (awaited)."""
        await self._load(case_id, must_be_open=True)
        return await self._run_analysis(case_id)

    async def reply(
        self,
        case_id: str,
        text: str,
        evidence_ids: list[str] | None = None,
        action_id: str | None = None,
        status: conversation.ReplyStatus | None = None,
    ) -> Case:
        """Apply the student's reply to the targeted (or oldest open) action and save it, then
        analyse in the background."""
        async with self._locks[case_id]:
            case = await self._load(case_id, must_be_open=True)
            case.actions = conversation.parse(case, text, evidence_ids or [], action_id, status)
            await self.repo.save(case)
        self._schedule(case_id)
        return case

    def running_agents(self, case_id: str) -> list[str]:
        """Agents that have started and not finished for this case (sorted)."""
        return sorted(self._running.get(case_id, ()))

    async def wait_idle(self) -> None:
        """Wait for every background analysis to finish (tests and graceful shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self) -> None:
        """Cancel background analyses that are still running (app shutdown)."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _schedule(self, case_id: str) -> None:
        """Start an analysis in the background, unless one is already waiting to start."""
        if case_id in self._queued:
            return
        self._queued.add(case_id)
        task = asyncio.create_task(self._background_analyse(case_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _background_analyse(self, case_id: str) -> None:
        """Run one analysis; a failure becomes a message to the student, never a crash."""
        try:
            await self._run_analysis(case_id, queued=True)
        except (CaseNotFoundError, CaseClosedError):
            return  # the case is gone or already decided: nothing left to analyse
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a background task must never die silently
            self.ctx.log.exception("analysis failed for case %s", case_id)
            await self._emit(
                case_id,
                OrchestratorMessage(
                    text="One of the checks failed to run. Your evidence is saved: "
                    "send another message or upload to try again."
                ),
            )

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

    async def _run_analysis(self, case_id: str, *, queued: bool = False) -> Case:
        """Run the agents on a snapshot (slow, no state lock), then apply the results to the
        latest stored case under the short state lock, so evidence or answers that arrived
        meanwhile are kept. Agents whose inputs changed meanwhile rerun on the next analysis."""

        async def publish(event: StreamEvent) -> None:
            if isinstance(event, AgentStarted):
                self._running[case_id].add(event.agent)
            elif isinstance(event, AgentFinished):
                self._running[case_id].discard(event.report.agent)
            await self._emit(case_id, event)

        async with self._analysis_locks[case_id]:
            if queued:
                self._queued.discard(case_id)  # later requests must schedule a fresh analysis
            snapshot = await self._load(case_id, must_be_open=True)
            try:
                new_reports = await run_agents(snapshot, self.agents, self.ctx, publish)
            finally:
                self._running.pop(case_id, None)
            async with self._locks[case_id]:
                case = await self._load(case_id, must_be_open=True)
                return await self._finish_analysis(case, new_reports)

    async def _finish_analysis(self, case: Case, new_reports: dict[str, AgentReport]) -> Case:
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
