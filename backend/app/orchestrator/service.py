"""CaseService: the use cases the API calls. Every state change is saved, then published."""

import asyncio
import hashlib
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from app.aggregators.consultant.consultant import already_answered, propose_actions
from app.aggregators.crosschecker import crosschecker, disagreements
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
    CheckState,
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
from app.intake import email_pdf, images, ocr, pdf
from app.intake.service import attach, extract
from app.orchestrator import checks as checks_mod
from app.orchestrator import (
    composer,
    conversation,
    crosscheck,
    debrief,
    decision,
    fields,
    payment_confirmation,
    rounds,
)
from app.orchestrator.composer import RoundInput, RoundNote
from app.orchestrator.events import EventBus
from app.orchestrator.runner import run_agents
from app.storage.repository import CaseRepository, InitialUpload

# NOTE: the LLM steps of a round get their own deadlines, because the LLM client's default
# timeout is minutes and a hung call would hold the analysis lock for that long.
CROSSCHECK_TIMEOUT_S = 30.0
CONSULTANT_TIMEOUT_S = 30.0

CONFIRM_PAYMENT_TEXT = (
    "Your messages mention a payment concern. Please answer the question below. Only a yes "
    "confirms it; a no or unsure keeps it on record and we move on to the next checks."
)

FAILED_ANALYSIS_TEXT = (
    "One of the checks failed to run. Your evidence is saved: "
    "send another message or upload to try again."
)


# What the student is told when an upload could not be read (keys: intake OCRError reasons).
_READ_FAILURES = {
    email_pdf.OCR_FAILED: (
        "I couldn't read every scanned page in that email PDF. Retry the file, upload a clearer "
        "PDF or screenshots, or paste the email. No partial email was analysed."
    ),
    email_pdf.LIMIT: (
        "That email PDF exceeds the reading limits (10 MB, 20 pages, at most 5 scanned pages), "
        "or is password protected. Upload a smaller unlocked PDF or paste the email."
    ),
    pdf.UNREADABLE: (
        "I couldn't read that email PDF. Upload a PDF with selectable text, paste the email, "
        "or upload clear screenshots of its pages."
    ),
    ocr.NOT_A_CHAT: (
        "That image doesn't look like a chat. If it's a document, upload it as a document instead."
    ),
    ocr.NOT_A_DOCUMENT: (
        "I couldn't find any text in that image. If it's a chat, upload it as messages."
    ),
    ocr.UNREADABLE: (
        "I couldn't read that screenshot clearly. Try a sharper screenshot, or export the chat "
        "as text."
    ),
    images.UNSUPPORTED: "I can't open that image type. Please upload a PNG or JPG screenshot.",
    images.TOO_BIG: "That image is too large. Please upload a smaller screenshot (under 5 MB).",
    images.EMPTY: "That file looks empty. Please try uploading it again.",
    ocr.TIMEOUT: "Reading that image took too long. Please try again in a moment.",
    ocr.LLM_ERROR: "I couldn't read that image right now. Please try again in a moment.",
    ocr.ZIP: 'Couldn\'t find the chat text in that zip. Export the chat again "Without media".',
}
_UNREADABLE_DOCUMENT = (
    "I couldn't read that image clearly. Try a sharper photo, or upload the PDF or Word file."
)
_CHAT_KINDS = (EvidenceKind.CHAT_SCREENSHOT, EvidenceKind.CHAT_EXPORT)


def failure_message(kind: EvidenceKind, reason: str) -> str:
    """The student-facing message for an upload that could not be read (any reason)."""
    if reason == ocr.UNREADABLE and kind not in _CHAT_KINDS:
        return _UNREADABLE_DOCUMENT
    return _READ_FAILURES.get(reason, _READ_FAILURES[ocr.LLM_ERROR])


RETIRED_ANSWER = "No longer needed: your evidence already covers this."
PROVIDED_ANSWER = "Done: you have already provided this."


class CaseNotFoundError(Exception):
    """No case with this id (HTTP 404)."""


STILL_OPEN_TEXT = "You can still add files, paste messages or ask me anything: I will check again."
VERDICT_STANDS_TEXT = "My verdict stays the same for now."
NOTED_TEXT = "I've noted that."
VERDICT_MEMORY_TURNS = 8  # how far back a verdict counts as already told


class CaseClosedError(Exception):
    """The case is already decided (HTTP 409)."""


class UploadConflictError(Exception):
    """An initial attachment still needs attention, or does not match its reservation."""


@dataclass(frozen=True)
class Upload:
    """One thing the student uploaded or pasted."""

    kind: EvidenceKind
    data: bytes
    filename: str | None = None
    note: str | None = None
    student_name: str | None = None
    request_id: str | None = None
    retry_read: bool = False


@dataclass(frozen=True)
class UploadResult:
    """An upload receipt without changing the shared Case or Evidence schemas."""

    case: Case
    evidence_id: str
    read_error: str | None


def _upload_id(upload: Upload) -> str | None:
    """Bind retries to the same request and bytes, without storing file contents in metadata."""
    if upload.request_id is None:
        return None
    digest = hashlib.sha256()
    for value in (upload.request_id, upload.kind.value, upload.filename, upload.note):
        digest.update((value or "").encode())
        digest.update(b"\0")
    digest.update(upload.data)
    return f"ev_upload_{digest.hexdigest()[:32]}"


def _existing_upload(case: Case, evidence_id: str | None) -> UploadResult | None:
    """Return the saved receipt after a lost response, even if the case has since closed."""
    evidence = next((e for e in case.evidence if e.id == evidence_id), None)
    if evidence is None:
        return None
    unreadable = not (evidence.extracted_text or "").strip() and evidence.kind not in (
        EvidenceKind.VIDEO,
        EvidenceKind.CALL_RECORDING,
    )
    return UploadResult(
        case,
        evidence.id,
        "File saved, but no readable text was extracted. Upload a text-based file or a clearer "
        "screenshot instead."
        if unreadable
        else None,
    )


def _all_findings(case: Case) -> list[Finding]:
    return [f for r in case.reports.values() for f in r.findings]


def _retire_settled(case: Case) -> list[Action]:
    """Close open steps the case has overtaken, so the student is never asked for something
    they already gave: a step whose check the evidence has cleared ("ask to view in person"
    after the chat shows the viewing happened) is skipped, and a step the case itself answers
    ("upload the contract" once one is uploaded) is done. Both are neutral, so neither changes
    a check, and a payment confirmation is never retired."""
    cleared = {c.id for c in case.checks if c.state == CheckState.CLEARED}
    answered = already_answered(case)

    def retire(action: Action) -> Action:
        if action.status != ActionStatus.OPEN or conversation.is_payment_confirmation(action.id):
            return action
        if action.id in answered:
            update = {"status": ActionStatus.DONE, "answer": PROVIDED_ANSWER}
        elif action.check_id in cleared:
            update = {"status": ActionStatus.SKIPPED, "answer": RETIRED_ANSWER}
        else:
            return action
        return action.model_copy(update={**update, "outcome": "neutral"})

    return [retire(a) for a in case.actions]


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
        # Cross-checker disagreements already relayed to the student, per case.
        self._relayed: dict[str, list[Finding]] = {}

    async def _load(self, case_id: str, *, must_be_open: bool = False) -> Case:
        case = await self.repo.get(case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        if must_be_open and case.status == "decided":
            raise CaseClosedError(case_id)
        return case

    async def _load_for_input(self, case_id: str) -> Case:
        """Load a case the student is adding to. A decided case is reopened (in memory; the
        caller saves it): a verdict never locks the student out, and whatever they add is
        analysed and decided again. Hard flags stay in the reports, so they still decide."""
        case = await self._load(case_id)
        if case.status == "decided":
            case.status = "open"
            case.decision = None
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
        *,
        initial_uploads: list[InitialUpload] | None = None,
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
        await self.repo.create(case, uploads=initial_uploads)
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

    async def get_uploads(self, case_id: str) -> list[InitialUpload]:
        """Return durable initial upload progress, including on a different device."""
        await self._load(case_id)
        return await self.repo.get_uploads(case_id)

    async def skip_upload(self, case_id: str, request_id: str) -> list[InitialUpload]:
        """Release one failed/interrupted attachment only after the student's explicit choice."""
        async with self._locks[case_id]:
            case = await self._load(case_id)
            uploads = await self.repo.get_uploads(case_id)
            item = next((u for u in uploads if u.request_id == request_id), None)
            if item is None:
                raise CaseNotFoundError(request_id)
            if item.state != "pending":
                return uploads  # idempotent after a lost response or completed upload
            if case.status == "decided":
                case.status = "open"  # reopened: the next analysis decides again
                case.decision = None
            item.state = "skipped"
            # Skipping records no clear: unreadable evidence remains visible as unreadable.
            await self.repo.save(case, uploads=uploads)
            self._schedule(case_id)
        return uploads

    async def _upload_manifest(self, case_id: str, upload: Upload) -> list[InitialUpload]:
        uploads = await self.repo.get_uploads(case_id)
        item = next((u for u in uploads if u.request_id == upload.request_id), None)
        if item is not None and (
            item.state != "pending"
            or item.filename != upload.filename
            or item.kind != upload.kind
            or item.size != len(upload.data)
            or item.note != upload.note
        ):
            raise UploadConflictError(
                "This file does not match the initial attachment, or it was skipped. "
                "Select the original file, or add a different file using Add evidence."
            )
        return uploads

    async def add_evidence(self, case_id: str, upload: Upload) -> Case:
        """Read, save and analyse one upload; preserve the original Case-only service API."""
        return (await self.accept_evidence(case_id, upload)).case

    async def accept_evidence(self, case_id: str, upload: Upload) -> UploadResult:
        """Read an upload (text and messages) and save it, then analyse in the background.

        The read (a vision call for images, 5 to 15 s) runs before the state lock is taken, so
        replies and other uploads to the case are not blocked by it. An image that cannot be read
        is still saved, with a message telling the student what to do, and starts no analysis.
        """
        evidence_id = _upload_id(upload)
        case = await self._load(case_id)
        previous = _existing_upload(case, evidence_id)
        if previous and (not upload.retry_read or not previous.read_error):
            return previous
        await self._upload_manifest(case_id, upload)
        extracted = await extract(
            upload.kind, upload.filename, upload.data, upload.student_name, self.ctx.llm
        )
        if evidence_id:
            extracted = replace(
                extracted,
                evidence_id=evidence_id,
                messages=[
                    m.model_copy(update={"evidence_id": evidence_id}) for m in extracted.messages
                ],
            )
        events: list[StreamEvent] = []
        async with self._locks[case_id]:
            case = await self._load(case_id)  # another attempt may already have saved the file
            previous = _existing_upload(case, evidence_id)
            if previous and (not upload.retry_read or not previous.read_error):
                return previous
            # NOTE: evidence added after a verdict reopens the case; it is decided again.
            case = await self._load_for_input(case_id)
            uploads = await self._upload_manifest(case_id, upload)
            if previous:
                # Only a failed read may be retried in place; readable evidence is immutable.
                case.evidence = [e for e in case.evidence if e.id != evidence_id]
                case.messages = [m for m in case.messages if m.evidence_id != evidence_id]
            case = await attach(
                case, upload.kind, upload.filename, upload.data, upload.note, extracted
            )
            saved = _existing_upload(case, extracted.evidence_id)
            assert saved is not None
            read_error = (
                failure_message(upload.kind, extracted.error)
                if extracted.error
                else saved.read_error
            )
            if read_error:
                events.append(_say(case, read_error))
            for item in uploads:
                if item.request_id == upload.request_id:
                    item.evidence_id = extracted.evidence_id
                    item.read_error = read_error
                    item.state = "pending" if read_error else "accepted"
            await self.repo.save(case, uploads=uploads)
            if not read_error:
                # Queue while holding the state lock: an older round cannot decide before rerun.
                self._schedule(case_id)
        await self._emit_all(case_id, events)
        return UploadResult(case, extracted.evidence_id, read_error)

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
        snapshot = await self._load_for_input(case_id)
        # NOTE: read_reply checks `action_id` first (InvalidActionError, 422) before any LLM call.
        result = await conversation.read_reply(snapshot, text, ids, action_id, status, self.ctx)

        async with self._locks[case_id]:
            case = await self._load_for_input(case_id)
            case.actions, dropped = conversation.apply(case.actions, result, text)
            changed_fields = fields.apply_fields(case, result.field_updates)
            answered = [u.action_id for u in result.updates if u.action_id not in dropped]
            case.chat.append(
                ChatTurn(role="student", text=text, at=datetime.now(UTC), action_ids=answered)
            )
            await self.repo.save(case)
            checks = {a.id: a.check_id for a in case.actions}
            self._notes[case_id].extend(
                [*changed_fields, *rounds.reply_notes(result, dropped, text, checks)]
            )
        self._schedule(case_id)
        return case

    async def debrief(self, case_id: str, call: debrief.CallDebrief) -> Case:
        """Save a finished voice call and apply what it answered, then analyse in the background
        (plan WS V 4.2).

        The transcript becomes one `call_recording` evidence item, the student's lines become
        messages and every line a chat turn. Explicit answers are applied first, then the
        student's side is read like a chat reply. Every parse runs on a snapshot without the
        state lock, like `reply`. Only the short thanks message is emitted over the stream.
        """
        snapshot = await self._load_for_input(case_id)
        # NOTE: mask first, so nothing stored or sent to an LLM holds a full bank account.
        call = debrief.masked(call)
        if not call.lines:
            return snapshot  # nothing was said: nothing to save
        evidence_id = new_id("ev")
        evidence = debrief.build_evidence(evidence_id, call.lines, datetime.now(UTC))
        messages = debrief.build_messages(evidence_id, call.lines)
        turns = debrief.build_chat_turns(call.lines)

        # Explicit answers first (like an action-card reply), each on a working copy where the
        # earlier ones are already applied, so the transcript reading only sees what is still open.
        kept, dropped_ids = debrief.split_answers(snapshot, call.answers)
        working = snapshot.model_copy(deep=True)
        readings: list[tuple[conversation.ParseResult, str, bool]] = []
        for answer in kept:
            try:
                result = await conversation.read_reply(
                    working,
                    answer.answer,
                    [evidence_id],
                    answer.action_id,
                    answer.status,
                    self.ctx,
                )
            except conversation.InvalidActionError:
                dropped_ids.append(answer.action_id)
                continue
            except Exception as exc:  # noqa: BLE001 - the call must be saved whatever happens
                self.ctx.log.warning("debrief answer parse failed: %s", type(exc).__name__)
                continue
            working.actions, _ = conversation.apply(working.actions, result, answer.answer)
            readings.append((result, answer.answer, False))

        text = debrief.student_text(call.lines)
        # NOTE: a call where the student said only a few words ("Yes.") is not read: a bare
        # answer would target an open payment confirmation, and a stray yes must not confirm a
        # hard flag. Answers recorded during the call still apply, and the agents still read it.
        if text and not conversation.is_short_answer(text):
            try:
                if any(a.status == ActionStatus.OPEN for a in working.actions):
                    transcript = await conversation.read_reply(
                        working, text, [evidence_id], None, None, self.ctx
                    )
                else:
                    # No step left to answer: the call can still give a company number, a
                    # name, the rent, the deposit or the move-in date.
                    transcript = await conversation.read_fields_only(text, self.ctx)
            except Exception as exc:  # noqa: BLE001 - the transcript must be saved whatever happens
                # Log the error type only: messages can echo the student's words.
                self.ctx.log.warning("debrief parse failed: %s", type(exc).__name__)
                transcript = conversation.ParseResult()
            if transcript.used_fallback:
                # NOTE: keywords guess which step a reply answers. A whole call is a story, not
                # a reply to one step, so that guess is not applied: the transcript, the
                # recorded answers and the agents' reading of it are kept, the guess is not.
                transcript = conversation.ParseResult(
                    field_updates=transcript.field_updates,
                    invalid_fields=transcript.invalid_fields,
                )
            readings.append((transcript, text, True))

        async with self._locks[case_id]:
            case = await self._load_for_input(case_id)
            case.evidence.append(evidence)
            case.messages.extend(messages)
            case.chat.extend(turns)
            applied = 0
            changed_fields: list[RoundNote] = []
            notes: list[RoundNote] = []
            for result, reading_text, is_transcript in readings:
                # A call is a story, not a reply to one step: matching no step needs no note.
                skip = {"dropped", "unmatched"} if is_transcript else {"dropped"}
                case.actions, dropped = conversation.apply(case.actions, result, reading_text)
                dropped_ids.extend(dropped)
                applied += sum(1 for u in result.updates if u.action_id not in dropped)
                changed = fields.apply_fields(case, result.field_updates)
                changed_fields.extend(changed)
                checks = {a.id: a.check_id for a in case.actions}
                notes.extend(
                    n
                    for n in rounds.reply_notes(result, dropped, reading_text, checks)
                    if n.kind not in skip
                )
            if dropped_ids:
                notes.append(RoundNote(kind="dropped"))  # once, not per action
            event = _say(case, debrief.THANKS_TEXT)
            await self.repo.save(case)
            # NOTE: one call gives several readings; the same note from two of them (e.g. two
            # upload hints) must not become the same sentence twice in the round message.
            summary = debrief.summary_note(applied, len(changed_fields))
            all_notes = [*notes, *changed_fields, summary]
            self._notes[case_id].extend(dict.fromkeys(all_notes))
        # Only the thanks message: the browser already showed the call's own lines.
        await self._emit(case_id, event)
        self._schedule(case_id)
        return case

    def running_agents(self, case_id: str) -> list[str]:
        """Agents that have started and not finished for this case (sorted)."""
        return sorted(self._running.get(case_id, ()))

    async def wait_idle(self) -> None:
        """Wait for every background analysis to finish (tests and graceful shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
            # NOTE: gather returns without yielding when every task is already done, so give the
            # loop a turn to run their done callbacks (which remove them); else this could spin.
            await asyncio.sleep(0)

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
            if any(u.state == "pending" for u in await self.repo.get_uploads(case_id)):
                raise UploadConflictError(
                    "Initial attachments still need attention. Retry each file or choose "
                    "Continue without this file before requesting a final decision."
                )
            return await self._decide(case)

    async def _decide(self, case: Case, reply: str | None = None) -> Case:
        """Decide and tell the student. `reply` (not None when the student's message led to this
        round) is the answer to what they said: it goes first, and a verdict they were already
        told is not repeated word for word, so the chat never looks stuck on one message."""
        if case.case_id in self._queued or any(
            u.state == "pending" for u in await self.repo.get_uploads(case.case_id)
        ):
            return case  # all initial files must be resolved, and newer evidence analysed first
        if payment_confirmation.awaiting(case) and not decision.hard_flags(case):
            return await self._confirm_payment(case)
        case.decision = decision.decide(case)
        case.status = "decided"
        # The student spoke last (an answer, a question, a call): tell them the outcome in the
        # chat too, so a verdict never looks like a chat that stopped replying.
        said = None
        summary = case.decision.summary
        if reply is not None:
            told = any(
                t.role == "orchestrator" and summary in t.text
                for t in case.chat[-VERDICT_MEMORY_TURNS:]
            )
            tail = VERDICT_STANDS_TEXT if told else f"{summary} {STILL_OPEN_TEXT}"
            said = _say(case, f"{reply or NOTED_TEXT} {tail}")
        elif case.chat and case.chat[-1].role == "student":
            said = _say(case, f"{summary} {STILL_OPEN_TEXT}")
        await self.repo.save(case)
        if said:
            await self._emit(case.case_id, said)  # `decision_made` stays the last event
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

    def _relayable_recap(
        self, case_id: str, previous: AgentReport | None, cross: AgentReport
    ) -> str | None:
        """The recap to relay this round: only when it brings a disagreement not relayed before
        (a reworded recap or a reordered set is not one), and within the student-facing rules.

        What was relayed is kept in memory per case; after a restart it starts from the previous
        report, whose recap is taken as relayed.
        """
        seen = self._relayed.get(case_id)
        if seen is None:
            seen = disagreements.of_report(previous) if previous and previous.summary else []
            self._relayed[case_id] = seen
        recap = cross.summary
        fresh = disagreements.unseen(disagreements.of_report(cross), seen)
        if not recap or not fresh:
            return None
        violations = composer.validate_recap(recap)
        if violations:
            self.ctx.log.warning("recap not relayed: %s", ", ".join(violations))
            return None
        seen.extend(fresh)
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
            recap = self._relayable_recap(case_id, previous, cross)

            case.reports.update(new_reports)
            case.reports[crosschecker.NAME] = cross
            case.checks = checks_mod.update(case, _all_findings(case))
            case.actions = payment_confirmation.refresh(case)
            case.actions = _retire_settled(case)
            result = score(case.checks, self.weights)
            case.score_history.append(result)
            events: list[StreamEvent] = [ScoreUpdated(score=result)]
            if recap:
                events.append(_say(case, recap))
            await self.repo.save(case)
            await self._emit_all(case_id, events)
            hard = bool(decision.hard_flags(case))
            if hard and not notes:
                return await self._decide(case)
            confirming = not hard and bool(payment_confirmation.awaiting(case))
            if confirming:
                # A payment hard flag needs the student's explicit yes before it can decide.
                case = await self._confirm_payment(case)

        def verdict_input() -> RoundInput:
            """The round as the composer sees it when a verdict follows its message."""
            return rounds.round_input(
                score_before=score_before,
                score_after=result,
                states_before=states_before,
                checks_after=case.checks,
                new_reports=new_reports,
                fresh=[],
                actions=case.actions,
                recap_sent=recap is not None,
                notes=notes,
                case_grounding=rounds.grounding(case),
                case_history=rounds.history(case),
                previous_reports=snapshot.reports,
                deciding=True,
            )

        if hard:
            # The student said something and a hard flag still decides: answer them first.
            reply = await composer.compose_round(verdict_input(), self.ctx)
            async with self._locks[case_id]:
                case = await self._load(case_id, must_be_open=True)
                return await self._decide(case, reply)

        if confirming:
            # No new steps while the confirmation is open, but whatever the student just said
            # (a question, an answer, something we could not match) still gets a reply: a round
            # that says nothing looks like a chat that has stopped working.
            if not notes:
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
                notes=notes,
                case_grounding=rounds.grounding(case),
                case_history=rounds.history(case),
                previous_reports=snapshot.reports,
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
            reply = await composer.compose_round(verdict_input(), self.ctx) if notes else None
            return await self._decide_if_still_done(case_id, reply)
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
            case_history=rounds.history(case),
            previous_reports=snapshot.reports,
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

    async def _decide_if_still_done(self, case_id: str, reply: str | None = None) -> Case:
        """Decide, unless a reply reopened work while the consultant was thinking."""
        async with self._locks[case_id]:
            case = await self._load(case_id, must_be_open=True)
            if any(a.status == ActionStatus.OPEN for a in case.actions):
                return case  # cannot happen today (replies only close actions); kept for safety
            return await self._decide(case, reply)
