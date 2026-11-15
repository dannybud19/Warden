"""Read the student's chat reply: which open actions it answers, and how.

An LLM maps the reply onto the open actions (several at once for free text, one when the reply
targets an action). Every LLM step has a deterministic keyword fallback, so a round never blocks on
an LLM error. The flow is split so that the slow part never holds the case's state lock:

1. `validate_target` (sync, before anything else): unknown or closed `action_id` -> 422.
2. `read_reply` (async, may call the LLM, no lock): returns a `ParseResult`. `parse` is its
   deterministic keyword reading, synchronous, for callers that need no LLM.
3. `apply` (pure, under the lock, on the latest stored actions): returns the new action list.
"""

import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from functools import cache
from pathlib import Path
from typing import Literal

from app.contracts import Action, ActionStatus, Case
from app.core.agent import AgentContext
from app.orchestrator.fields import FieldUpdate, quote_found, read_fields
from app.orchestrator.models import LLMActionUpdate, LLMParseOutput, Outcome
from app.orchestrator.payment_confirmation import PREFIX as PAYMENT_CONFIRMATION_PREFIX

ReplyStatus = Literal["done", "skipped", "impossible"]

PARSE_TIMEOUT_S = 15.0
MAX_QUESTION_CHARS = 200

CLEARS = ("yes", "confirmed", "verified", "they did", "it is", "registered")
FLAGS = ("no", "refused", "won't", "wouldn't", "can't", "declined", "abroad")


class InvalidActionError(ValueError):
    """The reply names an action that does not exist or is no longer open (HTTP 422)."""


@dataclass(frozen=True)
class ActionUpdate:
    """One action the reply answers, already validated against the snapshot's open actions."""

    action_id: str
    status: ReplyStatus
    outcome: Outcome
    quote: str = ""  # the span of the student's text that supports the outcome ("" if none)
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParseResult:
    updates: tuple[ActionUpdate, ...] = ()
    question: str | None = None  # a question the student asked us, answered in the round message
    field_updates: tuple[FieldUpdate, ...] = ()  # case fields the student stated (plan 4.7)
    invalid_fields: tuple[str, ...] = ()  # labels of fields given but unusable, e.g. "rent"
    used_fallback: bool = False
    unmatched: bool = False  # free text that matched no open action


@cache
def parse_prompt() -> str:
    """The system prompt for the reply parser."""
    return (Path(__file__).parent / "prompts" / "parse.md").read_text(encoding="utf-8")


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![\w']){re.escape(word)}(?![\w'])", text) is not None


def keyword_outcome(text: str) -> Outcome:
    """Phase 0 keyword reading of a reply. Crude ("no problem" flags): the LLM's fallback only."""
    lowered = text.lower().replace("’", "'")
    if any(_has_word(lowered, w) for w in FLAGS):
        return "flags"
    if any(_has_word(lowered, w) for w in CLEARS):
        return "clears"
    return "neutral"


def validate_target(case: Case, action_id: str | None) -> None:
    """Raise InvalidActionError when `action_id` is given and is unknown or not open."""
    if action_id is None:
        return
    target = next((a for a in case.actions if a.id == action_id), None)
    if target is None:
        raise InvalidActionError(f"unknown action: {action_id}")
    if target.status != ActionStatus.OPEN:
        raise InvalidActionError(f"action is not open: {action_id}")


def is_payment_confirmation(action_id: str) -> bool:
    """A question asking the student to confirm a payment concern (`payment_confirmation`)."""
    return action_id.startswith(PAYMENT_CONFIRMATION_PREFIX)


def confirmation_outcome(text: str) -> Outcome:
    """A confirmation asks about a concern, so only a plain yes confirms it (a flag).

    Anything else (no, unsure, a longer answer) is neutral: it must never clear payment safety,
    and loose keywords must not confirm it. Same test as `payment_confirmation.confirmed`.
    """
    return "flags" if text.strip().lower().rstrip(".! ") == "yes" else "neutral"


_QUESTION_START = re.compile(
    r"^\s*(?:so\s*,?\s*|and\s+|but\s+|ok(?:ay)?\s*,?\s*)?"
    r"(?:what|why|how|who|when|where|which|is|are|was|were|do|does|did|can|could|should|"
    r"would|will|shall|may|might|am)\b",
    re.IGNORECASE,
)


def looks_like_question(text: str) -> bool:
    """True when the reply opens with a question to us ("what are the issues?", "is this
    normal"), so it is never recorded as the answer to an open action. Only the first sentence
    counts: "yes, the rent is 950. Is that normal?" is an answer first."""
    first = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    return first.endswith("?") or bool(_QUESTION_START.match(first))


SHORT_ANSWER_WORDS = 3


def is_short_answer(text: str) -> bool:
    """A bare answer like "yes", "no", "not sure": it can only mean the confirmation."""
    return len(text.split()) <= SHORT_ANSWER_WORDS


def _target(case: Case, action_id: str | None, text: str) -> str | None:
    """The action a reply is about: the one named, else an open payment confirmation for a bare
    answer (it must be answered before anything else), else None (free text over every open
    action, which may answer the confirmation too: only a plain yes ever confirms it).

    A question is never aimed at the confirmation: it goes to the reader with every open
    action, which picks up the question and answers nothing it does not answer.
    """
    if action_id is not None:
        return action_id
    if looks_like_question(text) or not is_short_answer(text):
        # NOTE: a longer reply ("they no longer want money first and the viewing is booked")
        # is read against every open action, the confirmation included, so nothing in it is lost.
        return None
    return next(
        (
            a.id
            for a in case.actions
            if a.status == ActionStatus.OPEN and is_payment_confirmation(a.id)
        ),
        None,
    )


def _with_confirmation_rule(result: ParseResult, text: str) -> ParseResult:
    """Replace the outcome of every done update to a payment confirmation by the plain-yes rule,
    whichever path (LLM or keywords) produced it."""
    updates = tuple(
        replace(u, outcome=confirmation_outcome(text))
        if u.status == "done" and is_payment_confirmation(u.action_id)
        else u
        for u in result.updates
    )
    return replace(result, updates=updates)


def _prompt_actions(case: Case, action_id: str | None) -> list[Action]:
    """The actions the LLM may answer: the targeted one, or every open action."""
    open_actions = [a for a in case.actions if a.status == ActionStatus.OPEN]
    if action_id is None:
        return open_actions
    return [a for a in open_actions if a.id == action_id]


def _payload(text: str, evidence_ids: list[str], actions: list[Action]) -> str:
    """The user message for the parse prompt (plan Appendix A)."""
    return json.dumps(
        {
            "reply": text,
            "evidence_ids": evidence_ids,
            "open_actions": [{"id": a.id, "text": a.text} for a in actions],
        },
        ensure_ascii=False,
    )


def _done(
    action_id: str, outcome: Outcome, quote: str, evidence_ids: Sequence[str]
) -> ActionUpdate:
    return ActionUpdate(action_id, "done", outcome, quote, tuple(evidence_ids))


def _fallback(actions: list[Action], text: str, evidence_ids: list[str]) -> ParseResult:
    """Keyword reading: only safe when exactly one action can be the one answered. A question
    answers nothing; it is kept so the round message can reply to it."""
    if looks_like_question(text):
        return ParseResult(used_fallback=True, question=_question(text))
    if len(actions) != 1:
        return ParseResult(used_fallback=True, unmatched=True)
    update = _done(actions[0].id, keyword_outcome(text), "", evidence_ids)
    return ParseResult(updates=(update,), used_fallback=True)


def _usable(raw: list[LLMActionUpdate], text: str) -> list[LLMActionUpdate]:
    """Updates whose quote is in the student's text, at most one per action (the first)."""
    seen: set[str] = set()
    kept: list[LLMActionUpdate] = []
    for update in raw:
        if update.action_id not in seen and quote_found(update.quote, text):
            seen.add(update.action_id)
            kept.append(update)
    return kept


def _to_updates(raw: list[LLMActionUpdate], evidence_ids: list[str]) -> tuple[ActionUpdate, ...]:
    """Convert to done updates; evidence ids per decision 13."""
    allowed = set(evidence_ids)
    listed = [tuple(dict.fromkeys(i for i in u.evidence_ids if i in allowed)) for u in raw]
    if not any(listed):
        # The LLM tied no file to any answer: every answer in this reply gets them all.
        listed = [tuple(evidence_ids)] * len(raw)
    return tuple(
        _done(u.action_id, u.outcome, u.quote, ids) for u, ids in zip(raw, listed, strict=True)
    )


def _question(raw: str | None) -> str | None:
    """The student's question to us, stripped and cut to 200 characters; None when blank."""
    question = (raw or "").strip()[:MAX_QUESTION_CHARS].rstrip()
    return question or None


def _read_actions(
    output: LLMParseOutput,
    actions: list[Action],
    text: str,
    evidence_ids: list[str],
    action_id: str | None,
    ctx: AgentContext,
) -> ParseResult:
    """The action part of a well-formed LLM reading (all-unknown ids take the fallback)."""
    prompt_ids = {a.id for a in actions}
    known = [u for u in output.updates if u.action_id in prompt_ids]
    if output.updates and not known:
        ctx.log.warning("parse fallback: %s", "unknown action ids")
        return _fallback(actions, text, evidence_ids)

    usable = _usable(known, text)
    if action_id is None:
        # In free text a neutral reading ("I'll ask them") must not close a step the student has
        # not done; only a reply to that step's own card can close it as neutral.
        usable = [u for u in usable if u.outcome != "neutral"]
    if usable:
        return ParseResult(updates=_to_updates(usable, evidence_ids))
    if action_id is not None:
        # The student did answer the targeted action, we just cannot read how.
        return ParseResult(updates=(_done(action_id, "neutral", "", evidence_ids),))
    return ParseResult(unmatched=True)


def _settled_without_llm(
    case: Case, evidence_ids: list[str], action_id: str | None, status: ReplyStatus | None
) -> ParseResult | None:
    """The result when the reply needs no reading: a skip or impossible, or nothing open."""
    if action_id is not None and status in ("skipped", "impossible"):
        return ParseResult(
            updates=(ActionUpdate(action_id, status, "neutral", "", tuple(evidence_ids)),)
        )
    if not _prompt_actions(case, action_id):
        return ParseResult(unmatched=True)
    return None


def _keyword_reading(actions: list[Action], text: str, evidence_ids: list[str]) -> ParseResult:
    """Keywords, then the payment-confirmation rule: the reading when no LLM answer is usable."""
    return _with_confirmation_rule(_fallback(actions, text, evidence_ids), text)


def parse(
    case: Case,
    text: str,
    evidence_ids: list[str],
    action_id: str | None = None,
    status: ReplyStatus | None = None,
) -> list[Action]:
    """The case's actions after a deterministic reading of the reply (no LLM, no I/O).

    Exactly what `read_reply` falls back to when the LLM fails, applied with `apply`. The case
    is not modified. Raises InvalidActionError for an unknown or closed `action_id`.
    """
    validate_target(case, action_id)
    target = _target(case, action_id, text)
    result = _settled_without_llm(case, evidence_ids, target, status) or _keyword_reading(
        _prompt_actions(case, target), text, evidence_ids
    )
    actions, _ = apply(case.actions, result, text)
    return actions


async def read_reply(
    case: Case,
    text: str,
    evidence_ids: list[str],
    action_id: str | None,
    status: ReplyStatus | None,
    ctx: AgentContext,
    *,
    today: date | None = None,
) -> ParseResult:
    """Map the reply onto the case's open actions, and read fields and a question (plan 4.3).

    Never raises except InvalidActionError (from `validate_target`). LLM errors, timeouts, bad
    JSON and all-unknown ids take the keyword reading (`parse`'s) and set `used_fallback`; that
    path reads no fields and no question. `today` (default: the real date) bounds the move-in
    date.

    An open payment confirmation is answered first: a reply without `action_id` targets it, and
    its outcome follows `confirmation_outcome` on both paths.
    """
    validate_target(case, action_id)
    action_id = _target(case, action_id, text)
    settled = _settled_without_llm(case, evidence_ids, action_id, status)
    if settled is not None:
        return settled

    actions = _prompt_actions(case, action_id)
    payload = _payload(text, evidence_ids, actions)
    try:
        output = await asyncio.wait_for(
            ctx.llm.complete_json(parse_prompt(), payload, LLMParseOutput), PARSE_TIMEOUT_S
        )
    except Exception as exc:  # any LLM failure: error, timeout, bad JSON, schema error
        # Log the error type only: messages can echo the student's text.
        ctx.log.warning("parse fallback: %s", type(exc).__name__)
        return _keyword_reading(actions, text, evidence_ids)

    result = _with_confirmation_rule(
        _read_actions(output, actions, text, evidence_ids, action_id, ctx), text
    )
    if result.used_fallback:
        return result
    field_updates, invalid = read_fields(output.fields, text, today or date.today())
    question = _question(output.question)
    # A reply that gives a field or asks a question is not unmatched, even with no action.
    answered_something = bool(field_updates or invalid or question)
    return replace(
        result,
        question=question,
        field_updates=field_updates,
        invalid_fields=invalid,
        unmatched=result.unmatched and not answered_something,
    )


def apply(actions: list[Action], result: ParseResult, text: str) -> tuple[list[Action], list[str]]:
    """Return (new action list, ids dropped because no longer open). Does not mutate `actions`.

    Each update whose action is still OPEN gets its status, outcome, `answer=text` and
    `answer_evidence_ids`.
    """
    new_actions = [a.model_copy(deep=True) for a in actions]
    by_id = {a.id: a for a in new_actions}
    dropped: list[str] = []
    for update in result.updates:
        target = by_id.get(update.action_id)
        if target is None or target.status != ActionStatus.OPEN:
            dropped.append(update.action_id)
            continue
        target.status = ActionStatus(update.status)
        target.outcome = update.outcome
        target.answer = text
        target.answer_evidence_ids = list(update.evidence_ids)
    return new_actions, dropped
