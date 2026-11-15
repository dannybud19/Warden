"""The round message: one short chat message to the student after each analysis that does not
decide. An LLM writes it from a small structured input; a validator rejects anything risky and a
deterministic template takes over (plan 4.4)."""

import asyncio
import json
import re
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from app.core.agent import AgentContext

COMPOSE_TIMEOUT_S = 10.0
MAX_WORDS = 60
MAX_RECAP_WORDS = 80

EM_DASH = "\u2014"  # the em dash character, written as an escape so no literal one is in the file
SCORE_SCALE = 100  # the "/100" in the score sentence
MAX_MOVED = 2
MAX_NOTES = 2
MAX_CHECKED = 2
MAX_FACT_WORDS = 8  # a note's text longer than this is replaced by a generic sentence

_BANNED = re.compile(
    # NOTE: explicit word forms, not `\w*`: "payment safety" is a check label and must pass.
    r"\b(safe|safely|safer|safest|legit|legitimate|legitimately|scam|scams|scammed|scammer|"
    r"scammers|genuine|genuinely|fraud|frauds|fraudulent|fraudster|fraudsters)\b",
    re.IGNORECASE,
)
_LONG_DIGITS = re.compile(r"\d{6,}")
_SPACE_BETWEEN_DIGITS = re.compile(r"(?<=\d) +(?=\d)")
_NUMBER = re.compile(r"\d+")

NoteKind = Literal[
    "unmatched",
    "dropped",
    "field_changed",
    "field_invalid",
    "question",
    "upload_hint",
    "answered",
]


@dataclass(frozen=True)
class CheckMove:
    check: str  # human label, e.g. "landlord identity"
    before: str  # CheckState value
    after: str


@dataclass(frozen=True)
class RoundNote:
    kind: NoteKind
    text: str = ""  # short plain fact, already masked, e.g. "rent set to 950"


@dataclass(frozen=True)
class RoundInput:
    score_before: int | None
    score_after: int
    moved: tuple[CheckMove, ...] = ()
    not_run: tuple[str, ...] = ()  # checks or agents that did not run this round
    checked: tuple[str, ...] = ()  # what was read this round and what it found, one line each
    new_actions: int = 0
    open_actions: int = 0
    recap_sent: bool = False  # a Cross-checker recap message went out just before this one
    notes: tuple[RoundNote, ...] = ()
    grounding: tuple[str, ...] = ()  # P2: findings (title: detail) and check states, to answer
    history: tuple[str, ...] = ()  # the last chat turns, so a follow-up question has its context
    deciding: bool = False  # a verdict message follows this one: only answer the student


@cache
def compose_prompt() -> str:
    """The system prompt for the round message."""
    return (Path(__file__).parent / "prompts" / "compose.md").read_text(encoding="utf-8")


async def compose_round(inp: RoundInput, ctx: AgentContext) -> str:
    """LLM message for this round; `template(inp)` on any error, timeout or violation."""
    try:
        reply = await asyncio.wait_for(
            ctx.llm.complete(compose_prompt(), _payload(inp)), COMPOSE_TIMEOUT_S
        )
    except Exception as exc:  # noqa: BLE001 - the round message must never fail
        return _fallback(inp, ctx, type(exc).__name__)
    text = drop_repeats(reply.strip(), inp.history)
    violations = validate(text, inp)
    if violations:
        return _fallback(inp, ctx, ", ".join(violations))
    return text


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_HISTORY_SELF = "you: "  # how `rounds.history` marks our own earlier turns


def _sentence_key(sentence: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()


def drop_repeats(text: str, history: tuple[str, ...]) -> str:
    """`text` without the sentences we already said in an earlier turn of `history`.

    The model sometimes answers an old question again or restates the last message word for
    word; repeating it reads as a stuck chat. An empty result fails `validate`, so the template
    takes over.
    """
    said = {
        _sentence_key(sentence)
        for turn in history
        if turn.startswith(_HISTORY_SELF)
        for sentence in _SENTENCE_END.split(turn[len(_HISTORY_SELF) :])
    }
    said.discard("")
    kept = [s for s in _SENTENCE_END.split(text) if _sentence_key(s) not in said]
    return " ".join(kept).strip()


def _payload(inp: RoundInput) -> str:
    """The user message for the LLM: the round input as JSON (plan Appendix B)."""
    return json.dumps(asdict(inp))


def _fallback(inp: RoundInput, ctx: AgentContext, reason: str) -> str:
    ctx.log.warning("compose fallback: %s", reason)
    return template(inp)


# Validator


def validate(text: str, inp: RoundInput) -> list[str]:
    """Names of the rules `text` breaks (empty list: OK to send)."""
    rules = (
        ("too_long", _too_long(text)),
        ("banned_word", _has_banned_word(text)),
        ("long_digits", _has_long_digits(text)),
        ("unknown_number", _has_unknown_number(text, inp)),
        ("empty", not text.strip()),
        ("em_dash", EM_DASH in text),
        ("not_prose", _not_prose(text)),
        ("false_new_steps", _claims_new_steps(text, inp)),
    )
    return [name for name, broken in rules if broken]


def validate_recap(text: str) -> list[str]:
    """Names of the rules a Cross-checker recap breaks before it is relayed (empty list: OK).

    The recap quotes no round input, so there is no number rule; the rest match `validate`.
    """
    rules = (
        ("too_long", len(text.split()) > MAX_RECAP_WORDS),
        ("banned_word", _has_banned_word(text)),
        ("long_digits", _has_long_digits(text)),
        ("empty", not text.strip()),
        ("em_dash", EM_DASH in text),
        ("not_prose", _not_prose(text)),
    )
    return [name for name, broken in rules if broken]


def _too_long(text: str) -> bool:
    return len(text.split()) > MAX_WORDS


def _has_banned_word(text: str) -> bool:
    return _BANNED.search(text) is not None


def _has_long_digits(text: str) -> bool:
    # "12 34 56" counts as one run of 6 digits
    return _LONG_DIGITS.search(_SPACE_BETWEEN_DIGITS.sub("", text)) is not None


def _has_unknown_number(text: str, inp: RoundInput) -> bool:
    return not _numbers(text) <= _allowed_numbers(inp)


_ADDED_STEPS = re.compile(r"\b(?:added|new)\b[^.]{0,25}\bsteps?\b", re.IGNORECASE)


def _claims_new_steps(text: str, inp: RoundInput) -> bool:
    """ "I've added 1 new step" when the round added none (the model miscounts open steps)."""
    return inp.new_actions == 0 and _ADDED_STEPS.search(text) is not None


def _not_prose(text: str) -> bool:
    # JSON or code fences, e.g. FakeLLM's default "{}", must never reach the student
    stripped = text.strip()
    return stripped.startswith(("{", "[")) or "```" in stripped


def _numbers(text: str) -> set[int]:
    return {int(n) for n in _NUMBER.findall(text)}


def _allowed_numbers(inp: RoundInput) -> set[int]:
    """Every number the message may mention: scores, their difference, counts and note facts."""
    allowed = {inp.score_after, inp.new_actions, inp.open_actions, SCORE_SCALE}
    if inp.score_before is not None:
        allowed |= {inp.score_before, abs(inp.score_after - inp.score_before)}
    sources = (*(note.text for note in inp.notes), *inp.grounding, *inp.history, *inp.checked)
    for source in sources:
        allowed |= _numbers(source)
    return allowed


# Template

_FIXED_NOTES: dict[NoteKind, str] = {
    "unmatched": "I couldn't match your message to a step.",
    "dropped": "That step was already closed.",
    "upload_hint": "Please upload that message so I can check it.",
    "question": "I can't answer that from your case yet.",
}

# kind -> (sentence with the fact, sentence when the fact can't be shown)
_FACT_NOTES: dict[NoteKind, tuple[str, str]] = {
    "field_changed": ("I updated: {}.", "I updated one detail."),
    "field_invalid": ("I couldn't use: {}.", "I couldn't use one detail."),
}


def template(inp: RoundInput) -> str:
    """Deterministic message for this round. Always passes `validate`."""
    if inp.deciding:  # the verdict message carries the status: only the reply to the student
        return " ".join(_note_sentences(inp.notes))
    parts = [
        _score_sentence(inp.score_before, inp.score_after),
        *_moved_sentences(inp.moved),
        _not_run_sentence(inp.not_run),
        *_checked_sentences(inp.checked),
        *_note_sentences(inp.notes),
        _actions_sentence(inp.new_actions, inp.open_actions),
    ]
    return " ".join(part for part in parts if part)


def _score_sentence(before: int | None, after: int) -> str:
    if before is None or before == after:
        return f"Your risk score is {after}/{SCORE_SCALE}."
    direction = "up" if after > before else "down"
    return f"Your risk score is now {after}/{SCORE_SCALE} ({direction} {abs(after - before)})."


def _moved_sentences(moved: tuple[CheckMove, ...]) -> list[str]:
    return [f"{_capitalise(m.check)} is now {m.after}." for m in moved[:MAX_MOVED]]


def _capitalise(label: str) -> str:
    return label[:1].upper() + label[1:]


def _not_run_sentence(not_run: tuple[str, ...]) -> str:
    return "I couldn't run every check this time." if not_run else ""


def _checked_sentences(checked: tuple[str, ...]) -> list[str]:
    """ "I checked the contract: nothing flagged." for each thing read this round."""
    return [f"I checked {line.rstrip('.')}." for line in checked[:MAX_CHECKED]]


def _note_sentences(notes: tuple[RoundNote, ...]) -> list[str]:
    rendered = (_note_sentence(note) for note in notes)
    return [sentence for sentence in rendered if sentence][:MAX_NOTES]


def _note_sentence(note: RoundNote) -> str:
    """One sentence for a note ("" for a kind the template does not know)."""
    if note.kind in _FIXED_NOTES:
        return _FIXED_NOTES[note.kind]
    if note.kind in _FACT_NOTES:
        with_fact, generic = _FACT_NOTES[note.kind]
        fact = note.text.strip().rstrip(".")
        return with_fact.format(fact) if _is_showable_fact(fact) else generic
    return ""


def _is_showable_fact(fact: str) -> bool:
    """True when quoting the fact keeps the template inside every validator rule."""
    return (
        bool(fact)
        and len(fact.split()) <= MAX_FACT_WORDS
        and not _has_banned_word(fact)
        and not _has_long_digits(fact)
        and EM_DASH not in fact
        and not _not_prose(fact)
    )


def _actions_sentence(new: int, open_: int) -> str:
    if new > 0:
        return f"I've added {new} new {_steps(new)} below."
    if open_ > 0:
        verb = "is" if open_ == 1 else "are"
        return f"{open_} {_steps(open_)} {verb} still open below."
    return ""


def _steps(n: int) -> str:
    return "step" if n == 1 else "steps"
