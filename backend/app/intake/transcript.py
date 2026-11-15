"""Pasted chat that is not a WhatsApp export: one "Name: message" per line.

Students copy chats out of WhatsApp Web, iMessage, Telegram or an email thread, so the text has no
export timestamps. Without this the whole paste became one message from an unknown sender and the
checkers, which only read what the agent wrote, flagged nothing.
"""

import re

from app.contracts import Message
from app.core.ids import new_id
from app.intake.whatsapp import student_senders

# An optional "[14:02, 14/11/2026]" style prefix (WhatsApp Web copy), then "Name: message".
# A name is one to four short words that start with a letter, so "https://..." and
# "Rent: £850" style lines inside a message are not mistaken for a new speaker.
_LINE = re.compile(
    r"^(?:\[[^\]\n]{1,40}\]\s*)?"
    r"(?P<name>[^\W\d_][\w.'’+-]*(?: [\w.'’+()-]+){0,3}) ?: (?P<body>\S.*)$"
)
_SELF_NAMES = {"me", "you", "myself", "i"}
MAX_SPEAKERS = 4


def _key(name: str) -> str:
    return " ".join(name.lower().split())


def parse_transcript(text: str, evidence_id: str, student_name: str | None) -> list[Message]:
    """Messages from a "Name: message" transcript, or [] when the text is not one.

    It counts as a transcript only when the first line names a speaker, at least two people speak
    and every speaker label is used by one of at most four people. `student_name` (or "Me"/"You")
    decides which side is the student; with no match everyone is the agent, as for exports.
    """
    lines = [raw.rstrip() for raw in text.splitlines()]
    lines = [line for line in lines if line.strip()]
    if not lines or not _LINE.match(lines[0]):
        return []
    # Pass 1: who speaks. A label used once among several lines by the same people is a speaker
    # only if it opens a line; labels beyond the cap mean this is prose, not a chat.
    counts: dict[str, int] = {}
    for line in lines:
        if match := _LINE.match(line):
            counts[_key(match["name"])] = counts.get(_key(match["name"]), 0) + 1
    first = _key(_LINE.match(lines[0])["name"])  # type: ignore[index]
    speakers = {name for name, n in counts.items() if n > 1 or name == first}
    if len(counts) == 2:
        speakers = set(counts)  # a two-line exchange: each person speaks once
    if not 2 <= len(speakers) <= MAX_SPEAKERS:
        return []

    names: list[str] = []
    messages: list[Message] = []
    for line in lines:
        match = _LINE.match(line)
        if match and _key(match["name"]) in speakers:
            names.append(match["name"].strip())
            messages.append(
                Message(
                    id=new_id("msg"),
                    evidence_id=evidence_id,
                    sender="agent",
                    channel="other",
                    text=match["body"].strip(),
                )
            )
        else:
            last = messages[-1]
            messages[-1] = last.model_copy(update={"text": f"{last.text}\n{line.strip()}"})
    student = student_senders(names, student_name) | {n for n in names if _key(n) in _SELF_NAMES}
    return [
        m.model_copy(update={"sender": "student"}) if name in student else m
        for name, m in zip(names, messages, strict=True)
    ]
