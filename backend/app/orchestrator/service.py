"""CaseService: the use cases the API calls. Every state change is saved, then published."""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from app.aggregators.consultant.consultant import propose_actions
from app.aggregators.crosschecker import crosschecker
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
    ChatTurn,
    DecisionMade,
    EvidenceKind,
    Finding,
    Landlord,
    Listing,
    OrchestratorMessage,
    ScoreResult,
    ScoreUpdated,
    StreamEvent,
    StudentContext,
)
from app.core.agent import AgentContext, BaseAgent
from app.core.ids import new_id
from app.intake.service import ingest
from app.orchestrator import checks as checks_mod
from app.orchestrator import (
    composer,
    conversation,
    crosscheck,
    decision,
    fields,
    payment_confirmation,
    rounds,
)
from app.orchestrator.composer import RoundNote
from app.orchestrator.events import EventBus
from app.orchestrator.runner import run_agents
from app.storage.repository import CaseRepository

# NOTE: the LLM steps of a round get their own deadlines, because the LLM client's default
# timeout is minutes and a hung call would hold the analysis lock for that long.
CROSSCHECK_TIMEOUT_S = 30.0
CONSULTANT_TIMEOUT_S = 30.0

CONFIRM_PAYMENT_TEXT = (
    "A payment concern needs your confirmation before we reach a decision. "
    "Answer the questions below; a no or unsure answer will keep it open for clarification."
)

FAILED_ANALYSIS_TEXT = (
    "One of the checks failed to run. Your evidence is saved: "
    "send another message or upload to try again."
)


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


def _all_findings(case: Case) -> list[Finding]:
    return [f for r in case.reports.values() for f in r.findings]


def _say(case: Case, text: str) -> OrchestratorMessage:
    """Record an orchestrator message in the case's chat and return its stream event.

    The caller saves the case before emitting the event, so a reload never loses a message the
    student has seen.
    """
    case.chat.append(ChatTurn(role="orchestrator", text=text, at=datetime.now(UTC)))
    return OrchestratorMessage(text=text)


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
        # is only ever held briefly: no agent run and no LLM call happens while it is held.
        # `_analysis_locks` makes sure one analysis runs at a time; it is held for the whole
        # (slow) analysis, so uploads and replies are never blocked by it.
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._analysis_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # Background analyses: strong references (so they are not garbage collected), the cases that
        # have one waiting to start (a second request would find the same latest state, so skip it),
        # and the agents currently running per case (replayed to a client that connects late).
        self._tasks: set[asyncio.Task[None]] = set()
        self._queued: set[str] = set()
        self._running: defaultdict[str, set[str]] = defaultdict(set)
        # What the next round message should mention about replies saved since the last analysis
        # started. In memory only: a restart loses at most one round's notes.
        self._notes: defaultdict[str, list[RoundNote]] = defaultdict(list)

    async def _load(self, case_id: str, *, must_be_open: bool = False) -> Case:
        case = await self.repo.get(case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        if must_be_open and case.status == "decided":
            raise CaseClosedError(case_id)
        return case

    async def _emit(self, case_id: str, event: StreamEvent) -> None:
        await self.bus.publish(case_id, event)

    async def _emit_all(self, case_id: str, events: list[StreamEvent]) -> None:
        for event in events:
            await self._emit(case_id, event)

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
        # Kept in the chat history: no stream is connected yet when a case opens.
        said = _say(case, note) if note else None
        await self.repo.create(case)
        await self._emit(case.case_id, ScoreUpdated(score=first))
        if said:
            await self._emit(case.case_id, said)
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
        """Apply the student's reply to the actions it answers and save it, then analyse in the
        background.

        The parse (which may call an LLM) runs on a snapshot without the state lock; its result
        is applied to the latest stored actions, so an action closed meanwhile is dropped (and
        the round message says so) instead of being overwritten.
        """
        ids = list(evidence_ids or [])
        snapshot = await self._load(case_id, must_be_open=True)
        # NOTE: read_reply checks `action_id` first (InvalidActionError, 422) before any LLM call.
        result = await conversation.read_reply(snapshot, text, ids, action_id, status, self.ctx)

        async with self._locks[case_id]:
            case = await self._load(case_id, must_be_open=True)
            case.actions, dropped = conversation.apply(case.actions, result, text)
            changed_fields = fields.apply_fields(case, result.field_updates)
            answered = [u.action_id for u in result.updates if u.action_id not in dropped]
            case.chat.append(
                ChatTurn(role="student", text=text, at=datetime.now(UTC), action_ids=answered)
            )
            await self.repo.save(case)
            self._notes[case_id].extend(
                [*changed_fields, *rounds.reply_notes(result, dropped, text)]
            )
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
            await self._report_failure(case_id)

    async def _report_failure(self, case_id: str) -> None:
        """Tell the student an analysis failed, recording it in the chat when the case loads."""
        event = OrchestratorMessage(text=FAILED_ANALYSIS_TEXT)
        try:
            async with self._locks[case_id]:
                case = await self._load(case_id, must_be_open=True)
                event = _say(case, FAILED_ANALYSIS_TEXT)
                await self.repo.save(case)
        except Exception:  # noqa: BLE001 - the message must still go out
            self.ctx.log.exception("could not record the failure message for case %s", case_id)
        await self._emit(case_id, event)

    async def decide(self, case_id: str) -> Case:
        """Close the case now, on what is verified so far (the student has the final say).

        Waits for a running analysis to finish first, so the decision sees its results.
        """
        await self._load(case_id, must_be_open=True)  # 404 / 409 at once, before waiting
        async with self._analysis_locks[case_id], self._locks[case_id]:
            case = await self._load(case_id, must_be_open=True)
            return await self._decide(case)

    async def _decide(self, case: Case) -> Case:
        if payment_confirmation.pending(case) and not decision.hard_flags(case):
            return await self._confirm_payment(case)
        case.decision = decision.decide(case)
        case.status = "decided"
        await self.repo.save(case)
        await self._emit(case.case_id, DecisionMade(decision=case.decision))
        return case

    async def _confirm_payment(self, case: Case) -> Case:
        """Keep the case open and ask about payment evidence even when the check is suspicious."""
        proposed = payment_confirmation.questions(case)
        if proposed:
            now = datetime.now(UTC)
            proposed = [action.model_copy(update={"asked_at": now}) for action in proposed]
            case.actions.extend(proposed)
            message = _say(case, CONFIRM_PAYMENT_TEXT)
            await self.repo.save(case)
            await self._emit_all(case.case_id, [ActionsProposed(actions=proposed), message])
        return case

    async def _run_analysis(self, case_id: str, *, queued: bool = False) -> Case:
        """Run the agents on a snapshot (slow, no state lock), then apply the results to the
        latest stored case, so evidence or answers that arrived meanwhile are kept. Agents whose
        inputs changed meanwhile rerun on the next analysis."""

        async def publish(event: StreamEvent) -> None:
            if isinstance(event, AgentStarted):
                self._running[case_id].add(event.agent)
            elif isinstance(event, AgentFinished):
                self._running[case_id].discard(event.report.agent)
            await self._emit(case_id, event)

        async with self._analysis_locks[case_id]:
            if queued:
                self._queued.discard(case_id)  # later requests must schedule a fresh analysis
            async with self._locks[case_id]:
                # NOTE: taken together under the lock, so these notes belong to exactly the
                # replies this snapshot contains.
                snapshot = await self._load(case_id, must_be_open=True)
                notes = self._notes.pop(case_id, [])
            try:
                new_reports = await run_agents(snapshot, self.agents, self.ctx, publish)
            finally:
                self._running.pop(case_id, None)
            return await self._finish_analysis(snapshot, new_reports, notes)

    async def _review(self, case: Case) -> AgentReport:
        """The Cross-checker's report: rule findings plus its recap.

        A failing or slow review keeps the rule findings, so the hard-flag rules still apply, and
        keeps the previous recap, so the same recap is not sent again next round.
        """
        rule_findings = crosscheck.compare(case, case.reports)
        try:
            return await asyncio.wait_for(
                crosschecker.review(case, rule_findings, self.ctx), CROSSCHECK_TIMEOUT_S
            )
        except Exception as exc:  # noqa: BLE001 - the round must not fail on the Cross-checker
            self.ctx.log.warning(
                "cross-checker failed (%s): rule findings only", type(exc).__name__
            )
            previous = case.reports.get(crosschecker.NAME)
            return AgentReport(
                agent=crosschecker.NAME,
                version=crosschecker.VERSION,
                status=AgentStatus.OK,
                input_hash="",
                findings=rule_findings,
                summary=previous.summary if previous else None,
            )

    def _relayable_recap(self, previous: str | None, current: str | None) -> str | None:
        """The recap to relay this round: changed, and within the student-facing rules."""
        recap = rounds.changed_recap(previous, current)
        if recap is None:
            return None
        violations = composer.validate_recap(recap)
        if violations:
            self.ctx.log.warning("recap not relayed: %s", ", ".join(violations))
            return None
        return recap

    async def _propose(self, case: Case, result: ScoreResult) -> list[Action] | None:
        """The consultant's next steps, or None when it failed or timed out.

        None is not "nothing left": it must not trigger a decision, so the round just asks
        nothing new and the next analysis tries again.
        """
        try:
            return await asyncio.wait_for(
                propose_actions(case, result, self.ctx), CONSULTANT_TIMEOUT_S
            )
        except Exception as exc:  # noqa: BLE001 - the round must not fail on the consultant
            self.ctx.log.warning("consultant failed (%s): no new steps", type(exc).__name__)
            return None

    async def _finish_analysis(
        self, snapshot: Case, new_reports: dict[str, AgentReport], notes: list[RoundNote]
    ) -> Case:
        """Score the round, relay the recap, then ask the next steps or decide.

        Three short locked steps with the LLM work (Cross-checker, consultant, composer) between
        them, so no LLM call ever holds the state lock. Event order: `score_updated`, the recap
        message (only if it changed), then `actions_proposed` (if any) and the round message, or
        `decision_made` instead of those two.
        """
        case_id = snapshot.case_id
        reviewed = snapshot.model_copy(update={"reports": {**snapshot.reports, **new_reports}})
        cross = await self._review(reviewed)

        # Step 1 (locked): reports, checks, score and recap on the latest stored case.
        async with self._locks[case_id]:
            case = await self._load(case_id, must_be_open=True)
            score_before = case.score_history[-1] if case.score_history else None
            states_before = {c.id: c.state for c in case.checks}
            previous = case.reports.get(crosschecker.NAME)
            recap = self._relayable_recap(previous.summary if previous else None, cross.summary)

            case.reports.update(new_reports)
            case.reports[crosschecker.NAME] = cross
            case.checks = checks_mod.update(case, _all_findings(case))
            result = score(case.checks, self.weights)
            case.score_history.append(result)
            events: list[StreamEvent] = [ScoreUpdated(score=result)]
            if recap:
                events.append(_say(case, recap))
            await self.repo.save(case)
            await self._emit_all(case_id, events)
            if decision.hard_flags(case):
                return await self._decide(case)
            confirming = bool(payment_confirmation.pending(case))
            if confirming:
                # A payment hard flag needs the student's explicit yes before it can decide.
                case = await self._confirm_payment(case)

        questions = [n for n in notes if n.kind == "question"]
        if confirming:
            # No new steps while the confirmation is open, but a question still gets an answer.
            if not questions:
                return case
            inp = rounds.round_input(
                score_before=score_before,
                score_after=result,
                states_before=states_before,
                checks_after=case.checks,
                new_reports=new_reports,
                fresh=[],
                actions=case.actions,
                recap_sent=recap is not None,
                notes=questions,
                case_grounding=rounds.grounding(case),
            )
            text = await composer.compose_round(inp, self.ctx)
            async with self._locks[case_id]:
                case = await self._load(case_id, must_be_open=True)
                event = _say(case, text)
                await self.repo.save(case)
                await self._emit(case_id, event)
                return case

        # Step 2 (no lock): next steps and the round message.
        existing = {a.id for a in case.actions}
        proposals = await self._propose(case, result)
        now = datetime.now(UTC)
        fresh = [
            a.model_copy(update={"asked_at": now}) for a in proposals or [] if a.id not in existing
        ]
        nothing_open = not any(a.status == ActionStatus.OPEN for a in case.actions)
        if proposals is not None and not fresh and nothing_open:
            return await self._decide_if_still_done(case_id)
        inp = rounds.round_input(
            score_before=score_before,
            score_after=result,
            states_before=states_before,
            checks_after=case.checks,
            new_reports=new_reports,
            fresh=fresh,
            actions=[*case.actions, *fresh],
            recap_sent=recap is not None,
            notes=notes,
            case_grounding=rounds.grounding(case),
        )
        text = await composer.compose_round(inp, self.ctx)

        # Step 3 (locked): store the new actions and the message on the latest case, then emit.
        # NOTE: only analyses add actions and they run one at a time, so `fresh` is still fresh.
        async with self._locks[case_id]:
            case = await self._load(case_id, must_be_open=True)
            case.actions.extend(fresh)
            events = [ActionsProposed(actions=fresh)] if fresh else []
            events.append(_say(case, text))
            await self.repo.save(case)
            await self._emit_all(case_id, events)
            return case

    async def _decide_if_still_done(self, case_id: str) -> Case:
        """Decide, unless a reply reopened work while the consultant was thinking."""
        async with self._locks[case_id]:
            case = await self._load(case_id, must_be_open=True)
            if any(a.status == ActionStatus.OPEN for a in case.actions):
                return case  # cannot happen today (replies only close actions); kept for safety
            return await self._decide(case)
