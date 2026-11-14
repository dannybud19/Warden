"""WhatsApp .txt export parser (iOS and Android formats, UK dd/mm/yy dates)."""

import re
from datetime import UTC, datetime

from app.contracts import Message
from app.core.ids import new_id

_IOS = re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4}), (\d{1,2}:\d{2}(?::\d{2})?)\] ([^:]+): (.*)$")
_ANDROID = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}), (\d{1,2}:\d{2}) - ([^:]+): (.*)$")
# A timestamp header with no "Sender:" part is a system line (encryption notice, group events).
_HEADER_ONLY = re.compile(
    r"^(?:\[\d{1,2}/\d{1,2}/\d{2,4}, \d{1,2}:\d{2}(?::\d{2})?\]|"
    r"\d{1,2}/\d{1,2}/\d{2,4}, \d{1,2}:\d{2} -) "
)
_SYSTEM_PHRASES = (
    "end-to-end encrypted",
    "created group",
    "added you",
    "changed the subject",
    "changed this group",
    "security code changed",
)
_INVISIBLE = dict.fromkeys(map(ord, "‎‏‪‫‬﻿"))


def _parse_time(date_str: str, time_str: str) -> datetime | None:
    day, month, year = (int(p) for p in date_str.split("/"))
    year += 2000 if year < 100 else 0
    parts = [int(p) for p in time_str.split(":")]
    try:
        # NOTE: exports carry no timezone; stored as UTC.
        return datetime(year, month, day, *parts, tzinfo=UTC)
    except ValueError:
        return None


def parse_export(text: str, evidence_id: str, student_name: str | None) -> list[Message]:
    """Messages from a WhatsApp export. `student_name` decides which side is the student."""
    student = (student_name or "").strip().lower()
    messages: list[Message] = []
    open_message = False  # True while continuation lines may still extend the last message
    for raw in text.translate(_INVISIBLE).splitlines():
        line = raw.rstrip()
        match = _IOS.match(line) or _ANDROID.match(line)
        if match:
            date_str, time_str, name, body = match.groups()
            if any(phrase in line.lower() for phrase in _SYSTEM_PHRASES):
                open_message = False
                continue
            sender = "student" if name.strip().lower() == student else "agent"
            messages.append(
                Message(
                    id=new_id("msg"),
                    evidence_id=evidence_id,
                    sender=sender,
                    sent_at=_parse_time(date_str, time_str),
                    channel="whatsapp",
                    text=body,
                )
            )
            open_message = True
        elif _HEADER_ONLY.match(line):
            open_message = False
        elif open_message and line:
            last = messages[-1]
            messages[-1] = last.model_copy(update={"text": f"{last.text}\n{line}"})
    return messages
