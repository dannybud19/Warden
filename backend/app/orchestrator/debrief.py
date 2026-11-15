"""Turn a finished voice call into case records: the transcript, messages, chat turns and notes.

Pure builders only (no I/O, no LLM). `CaseService.debrief` calls them; the reply parser
(`conversation.read_reply`) then reads the student's side of the call like a chat reply.
Every line is masked with `intake.redact.mask_sensitive` first, so a bank account said on the
call is never stored or sent to an LLM in full (phone and company numbers stay as they are).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

from app.contracts import ActionStatus, Case, ChatTurn, Evidence, EvidenceKind, Message
from app.core.ids import new_id
from app.intake.redact import mask_sensitive
from app.orchestrator.composer import RoundNote
from app.orchestrator.conversation import ReplyStatus

# The parser reads at most this much of the student's side of the call (the end: the latest
# answers). Every line is still stored in the evidence and the chat.
PARSER_MAX_CHARS = 8000
EVIDENCE_NOTE = "Voice call with Warden"
THANKS_TEXT = "Thanks, I've noted everything from our call. I'm checking it now."

Role = Literal["student", "orchestrator"]


@dataclass(frozen=True)
class CallLine:
    """One spoken turn of the call."""

    role: Role
    text: str
    at: datetime


@dataclass(frozen=True)
class CallAnswer:
    """An answer the voice agent recorded for one open action (`record_answer`)."""

    action_id: str
    answer: str
    status: ReplyStatus = "done"


@dataclass(frozen=True)
class CallDebrief:
    """Everything the browser sends when the call ends (`POST /cases/{id}/debrief`)."""

    lines: tuple[CallLine, ...]
    answers: tuple[CallAnswer, ...] = ()
    started_at: datetime | None = None
    source: Literal["call"] = "call"


def _mask(text: str) -> str:
    return mask_sensitive(text).strip()


def masked(call: CallDebrief) -> CallDebrief:
    """The same call with every line's text and every answer masked; blank lines dropped.

    Masking runs before anything is stored or sent to an LLM, so a bank account said on the
    call never leaves this function in full. Phone and company numbers are not masked.
    """
    lines = tuple(replace(line, text=text) for line in call.lines if (text := _mask(line.text)))
    answers = tuple(
        replace(answer, answer=text) for answer in call.answers if (text := _mask(answer.answer))
    )
    return replace(call, lines=lines, answers=answers)


def _utc(at: datetime) -> datetime:
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)


def transcript_text(lines: Sequence[CallLine]) -> str:
    """One line per turn: `[HH:MM] You: ...` / `[HH:MM] Warden: ...` (UTC)."""
    speaker = {"student": "You", "orchestrator": "Warden"}
    return "\n".join(f"[{_utc(ln.at):%H:%M}] {speaker[ln.role]}: {ln.text}" for ln in lines)


def student_text(lines: Sequence[CallLine], max_chars: int = PARSER_MAX_CHARS) -> str:
    """The student's lines joined with newlines, cut to the last `max_chars` characters."""
    text = "\n".join(line.text for line in lines if line.role == "student")
    return text[-max_chars:] if max_chars > 0 else ""


def build_evidence(evidence_id: str, lines: Sequence[CallLine], uploaded_at: datetime) -> Evidence:
    """The call as one `call_recording` evidence item with the transcript as extracted text."""
    return Evidence(
        id=evidence_id,
        kind=EvidenceKind.CALL_RECORDING,
        uploaded_at=uploaded_at,
        filename=None,
        extracted_text=transcript_text(lines),
        note=EVIDENCE_NOTE,
    )


def build_messages(evidence_id: str, lines: Sequence[CallLine]) -> list[Message]:
    """One `Message` per student line (`sender="student"`, `channel="call"`)."""
    return [
        Message(
            id=new_id("msg"),
            evidence_id=evidence_id,
            sender="student",
            sent_at=line.at,
            channel="call",
            text=line.text,
        )
        for line in lines
        if line.role == "student"
    ]


def build_chat_turns(lines: Sequence[CallLine]) -> list[ChatTurn]:
    """One `ChatTurn` per line, in order, with the line's own time."""
    return [ChatTurn(role=line.role, text=line.text, at=line.at, action_ids=[]) for line in lines]


def split_answers(case: Case, answers: Sequence[CallAnswer]) -> tuple[list[CallAnswer], list[str]]:
    """(answers whose action is open in `case`, ids dropped: unknown, closed or repeated)."""
    open_ids = {a.id for a in case.actions if a.status == ActionStatus.OPEN}
    kept: list[CallAnswer] = []
    seen: set[str] = set()
    dropped: list[str] = []
    for answer in answers:
        if answer.action_id in open_ids and answer.action_id not in seen:
            seen.add(answer.action_id)
            kept.append(answer)
        else:
            dropped.append(answer.action_id)
    return kept, dropped


def summary_note(answers: int, facts: int) -> RoundNote:
    """The round note `call debrief: N answers, M facts` (kind `answered`)."""
    return RoundNote(kind="answered", text=f"call debrief: {answers} answers, {facts} facts")
