"""Turn a finished voice call into case records: the transcript, messages, chat turns and notes.

Pure builders only (no I/O, no LLM). `CaseService.debrief` calls them; the reply parser
(`conversation.read_reply`) then reads the student's side of the call like a chat reply.
Every line is masked with `intake.redact.mask_sensitive` first, so a bank account said on the
call is never stored or sent to an LLM in full (phone and company numbers stay as they are).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.contracts import Case, ChatTurn, Evidence, Message
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


def masked(call: CallDebrief) -> CallDebrief:
    """The same call with every line's text and every answer masked; blank lines dropped."""
    raise NotImplementedError


def transcript_text(lines: Sequence[CallLine]) -> str:
    """One line per turn: `[HH:MM] You: ...` / `[HH:MM] Warden: ...` (UTC)."""
    raise NotImplementedError


def student_text(lines: Sequence[CallLine], max_chars: int = PARSER_MAX_CHARS) -> str:
    """The student's lines joined with newlines, cut to the last `max_chars` characters."""
    raise NotImplementedError


def build_evidence(evidence_id: str, lines: Sequence[CallLine], uploaded_at: datetime) -> Evidence:
    """The call as one `call_recording` evidence item with the transcript as extracted text."""
    raise NotImplementedError


def build_messages(evidence_id: str, lines: Sequence[CallLine]) -> list[Message]:
    """One `Message` per student line (`sender="student"`, `channel="call"`)."""
    raise NotImplementedError


def build_chat_turns(lines: Sequence[CallLine]) -> list[ChatTurn]:
    """One `ChatTurn` per line, in order, with the line's own time."""
    raise NotImplementedError


def split_answers(case: Case, answers: Sequence[CallAnswer]) -> tuple[list[CallAnswer], list[str]]:
    """(answers whose action is open in `case`, ids dropped: unknown, closed or repeated)."""
    raise NotImplementedError


def summary_note(answers: int, facts: int) -> RoundNote:
    """The round note `call debrief: N answers, M facts` (kind `answered`)."""
    raise NotImplementedError
