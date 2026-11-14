"""Pressure language a pattern can catch reliably, and the influence kinds. Pure functions."""

import re
from dataclasses import dataclass

from app.contracts import Case, Message

MAX_QUOTE = 200
NOTES_ID = "notes"  # message id the prompt uses for `student.notes`
NOTES_SOURCE = "student_notes"  # evidence id for quotes taken from the notes

AGENT_KINDS = ("urgency", "scarcity", "guilt", "authority", "jargon", "flattery")
STUDENT_KINDS = ("desperation", "sunk_cost")
# Flattery is shown but does not move the check on its own.
PRESSURE_KINDS = ("urgency", "scarcity", "guilt", "authority", "jargon")

TITLES = {
    "urgency": "Pushed to act now",
    "scarcity": "Told others are competing for it",
    "guilt": "Made to feel you owe something",
    "authority": "Credibility you cannot check",
    "jargon": "Wording that hides a plain meaning",
    "flattery": "Praise that lowers your guard",
    "desperation": "You are feeling short of time or options",
    "sunk_cost": "You have already invested a lot in this one",
}
DEFAULT_EXPLANATION = {
    "urgency": "This sets a deadline, which leaves you less time to check anything.",
    "scarcity": "Nobody can verify how many other people are interested. It is said to hurry you.",
    "desperation": "The time pressure you feel is real. It does not change whether this place "
    "is genuine.",
}

_I = re.IGNORECASE
_TRANS = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', " ": " "})
_BOUNDARY = re.compile(r"[.!?]+(?:\s+|$)|\n+")

_NOW = r"(?:today|tonight|now|immediately|asap|right away|straight away|within the hour)"
_ACT = r"(?:send|pay|decide|confirm|transfer|sign|act|reserve|book|commit)"
_URGENCY = re.compile(
    rf"\b{_ACT}\b[^.!?\n]{{0,40}}\b{_NOW}\b|\b{_NOW}\b[^.!?\n]{{0,25}}\b{_ACT}\b|"
    r"\bdecide (?:quickly|fast|soon)\b|\bbe quick\b|\bhurry\b|\bwon't last\b|"
    r"\bfirst come,? first served\b|"
    r"\b(?:or|otherwise) (?:it|I)(?:'ll| will)? (?:go|goes|give|offer)\b|"
    r"\blast chance\b",
    _I,
)
_SCARCITY = re.compile(
    r"\b(?:other|another|two|three|four|five|several|many|lots of|a lot of|\d+) "
    r"(?:other )?(?:students?|people|persons?|tenants?|applicants?|viewers|couples?|parties)\b"
    r"[^.!?\n]{0,30}\b(?:want|wants|interested|waiting|asking|ready|viewing|keen)\b|"
    r"\b(?:lots|a lot|plenty) of interest\b|\bhigh demand\b|\bgoing fast\b|\b(?:the )?last one\b|"
    r"\bsomeone else (?:is|has|wants)\b",
    _I,
)
_REASSURANCE = re.compile(
    r"\bno (?:rush|pressure|hurry)\b|\btake your time\b|\bwhenever you(?:'re| are) ready\b|"
    r"\bthink (?:it|about it) over\b",
    _I,
)
_DESPERATION = re.compile(
    r"\brunning out of (?:options|time)\b|\bdesperate\b|\bnowhere (?:else )?to (?:live|stay|go)\b|"
    r"\bneed (?:somewhere|a place|a room|it) (?:asap|urgently|quickly|fast|before|by)\b|"
    r"\b(?:term|my course|uni(?:versity)?) starts\b|\blast[- ]minute\b|\bhomeless\b",
    _I,
)
_SUNK_COST = re.compile(
    r"\balready (?:spent|paid|invested|wasted|sent)\b|\bafter all (?:this|the) (?:time|effort)\b|"
    r"\bcome this far\b",
    _I,
)
RULE_PATTERNS = {
    "urgency": _URGENCY,
    "scarcity": _SCARCITY,
    "desperation": _DESPERATION,
    "sunk_cost": _SUNK_COST,
}


@dataclass(frozen=True)
class Hit:
    """One quoted piece of influence (or reassurance) and where it came from."""

    kind: str
    source: str  # evidence id, or NOTES_SOURCE
    quote: str
    explanation: str = ""


def norm(text: str) -> str:
    """Straighten curly quotes without changing the length of the text."""
    return text.translate(_TRANS)


def quote_around(text: str, start: int, end: int) -> str:
    """The sentence(s) of `text` that contain `start:end`, as an exact substring of `text`."""
    bounds = [m.end() for m in _BOUNDARY.finditer(text)]
    left = max((b for b in bounds if b <= start), default=0)
    right = min((b for b in bounds if b >= end), default=len(text))
    if right - left > MAX_QUOTE:
        left, right = start, min(len(text), start + MAX_QUOTE)
    return text[left:right].strip()


def side_of(sender: str) -> tuple[str, ...]:
    """The influence kinds that can apply to a message from this sender."""
    return {"agent": AGENT_KINDS, "student": STUDENT_KINDS}.get(sender, ())


def _match(kind: str, pattern: re.Pattern[str], text: str, source: str) -> Hit | None:
    m = pattern.search(norm(text))
    if not m:
        return None
    return Hit(
        kind, source, quote_around(text, m.start(), m.end()), DEFAULT_EXPLANATION.get(kind, "")
    )


def _message_hits(message: Message) -> list[Hit]:
    allowed = side_of(message.sender)
    return [
        hit
        for kind, pattern in RULE_PATTERNS.items()
        if kind in allowed and (hit := _match(kind, pattern, message.text, message.evidence_id))
    ]


def rule_hits(case: Case) -> list[Hit]:
    """Urgency and scarcity from the agent; desperation and sunk cost from the student and notes."""
    hits = [hit for m in case.messages for hit in _message_hits(m)]
    notes = case.student.notes or ""
    for kind in STUDENT_KINDS:
        if hit := _match(kind, RULE_PATTERNS[kind], notes, NOTES_SOURCE):
            hits.append(hit)
    return hits


def reassurance_hits(case: Case) -> list[Hit]:
    """Agent messages that explicitly take the pressure off ("no rush")."""
    return [
        hit
        for m in case.messages
        if m.sender == "agent"
        and (hit := _match("reassurance", _REASSURANCE, m.text, m.evidence_id))
    ]
