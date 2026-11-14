"""Read the student's chat reply: which open actions it answers, and how.

An LLM maps the reply onto the open actions (several at once for free text, one when the reply
targets an action). Every LLM step has a deterministic keyword fallback, so a round never blocks on
an LLM error. The flow is split so that the slow part never holds the case's state lock:

1. `validate_target` (sync, before anything else): unknown or closed `action_id` -> 422.
2. `parse` (async, may call the LLM, no lock): returns a `ParseResult`.
3. `apply` (pure, under the lock, on the latest stored actions): returns the new action list.
"""

import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from app.contracts import Action, ActionStatus, Case
from app.core.agent import AgentContext
from app.orchestrator.fields import FieldUpdate
from app.orchestrator.models import LLMActionUpdate, LLMParseOutput, Outcome

ReplyStatus = Literal["done", "skipped", "impossible"]

PARSE_TIMEOUT_S = 15.0
MAX_QUOTE_CHARS = 200

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


# Curly quotes and apostrophes the LLM (or the student's keyboard) may use instead of straight ones.
_QUOTE_MAP = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


def _normalise(text: str) -> str:
    """Straight quotes, single spaces, case-folded: the form quotes are compared in."""
    return " ".join(text.translate(_QUOTE_MAP).split()).casefold()


def _quote_found(quote: str, text: str) -> bool:
    """True when `quote` is a non-empty, short span of the student's `text`."""
    needle = _normalise(quote)
    return bool(needle) and len(needle) <= MAX_QUOTE_CHARS and needle in _normalise(text)


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
    """Keyword reading: only safe when exactly one action can be the one answered."""
    if len(actions) != 1:
        return ParseResult(used_fallback=True, unmatched=True)
    update = _done(actions[0].id, keyword_outcome(text), "", evidence_ids)
    return ParseResult(updates=(update,), used_fallback=True)


def _usable(raw: list[LLMActionUpdate], text: str) -> list[LLMActionUpdate]:
    """Updates whose quote is in the student's text, at most one per action (the first)."""
    seen: set[str] = set()
    kept: list[LLMActionUpdate] = []
    for update in raw:
        if update.action_id not in seen and _quote_found(update.quote, text):
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


async def parse(
    case: Case,
    text: str,
    evidence_ids: list[str],
    action_id: str | None,
    status: ReplyStatus | None,
    ctx: AgentContext,
) -> ParseResult:
    """Map the reply onto the case's open actions (rules: plan 4.3).

    Never raises except InvalidActionError (from `validate_target`). LLM errors, timeouts, bad
    JSON and all-unknown ids take the keyword fallback and set `used_fallback`.
    """
    validate_target(case, action_id)
    if action_id is not None and status in ("skipped", "impossible"):
        update = ActionUpdate(action_id, status, "neutral", "", tuple(evidence_ids))
        return ParseResult(updates=(update,))

    actions = _prompt_actions(case, action_id)
    if not actions:
        return ParseResult(unmatched=True)

    payload = _payload(text, evidence_ids, actions)
    try:
        output = await asyncio.wait_for(
            ctx.llm.complete_json(parse_prompt(), payload, LLMParseOutput), PARSE_TIMEOUT_S
        )
    except Exception as exc:  # any LLM failure: error, timeout, bad JSON, schema error
        # Log the error type only: messages can echo the student's text.
        ctx.log.warning("parse fallback: %s", type(exc).__name__)
        return _fallback(actions, text, evidence_ids)

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
