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


def _words(name: str) -> list[str]:
    return name.strip().lower().split()


def student_senders(names: list[str], student_name: str | None) -> set[str]:
    """Which chat names are the student. An exact match (any case or spacing) wins; otherwise
    a first-name match, but only when exactly one person in the chat has that first name.

    The app knows the student by the name they typed (onboarding keeps only the first name),
    while the export shows their WhatsApp name, so "Georgi" must match "Georgi Roussinov".
    """
    wanted = _words(student_name or "")
    if not wanted:
        return set()
    exact = {n for n in names if _words(n) == wanted}
    if exact:
        return exact
    first = {n for n in names if _words(n)[:1] == wanted[:1]}
    people = {" ".join(_words(n)) for n in first}  # "Sam Reed" and "sam  reed" are one person
    return first if len(people) == 1 else set()


def parse_export(text: str, evidence_id: str, student_name: str | None) -> list[Message]:
    """Messages from a WhatsApp export. `student_name` decides which side is the student."""
    names: list[str] = []
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
            names.append(name)
            messages.append(
                Message(
                    id=new_id("msg"),
                    evidence_id=evidence_id,
                    sender="agent",  # settled below, once every name in the chat is known
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
    student = student_senders(names, student_name)
    return [
        m.model_copy(update={"sender": "student"}) if name in student else m
        for name, m in zip(names, messages, strict=True)
    ]
