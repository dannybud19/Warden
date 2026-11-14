"""Read the student's chat reply: which open actions it answers, and how.

An LLM maps the reply onto the open actions (several at once for free text, one when the reply
targets an action). Every LLM step has a deterministic keyword fallback, so a round never blocks on
an LLM error. The flow is split so that the slow part never holds the case's state lock:

1. `validate_target` (sync, before anything else): unknown or closed `action_id` -> 422.
2. `parse` (async, may call the LLM, no lock): returns a `ParseResult`.
3. `apply` (pure, under the lock, on the latest stored actions): returns the new action list.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from app.contracts import Action, ActionStatus, Case
from app.core.agent import AgentContext
from app.orchestrator.models import FieldName, Outcome

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
class FieldUpdate:
    """A validated, normalised case field taken from the reply (P2)."""

    field: FieldName
    value: str | int | date
    note: str  # short masked text for the round message, e.g. "rent set to 950"


@dataclass(frozen=True)
class ParseResult:
    updates: tuple[ActionUpdate, ...] = ()
    question: str | None = None  # P2; always None in P1
    field_updates: tuple[FieldUpdate, ...] = ()  # P2; always () in P1
    invalid_fields: tuple[str, ...] = ()  # P2: masked labels of fields we could not use
    used_fallback: bool = False
    unmatched: bool = False  # free text that matched no open action


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
    raise NotImplementedError


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
    raise NotImplementedError


def apply(actions: list[Action], result: ParseResult, text: str) -> tuple[list[Action], list[str]]:
    """Return (new action list, ids dropped because no longer open). Does not mutate `actions`.

    Each update whose action is still OPEN gets its status, outcome, `answer=text` and
    `answer_evidence_ids`.
    """
    raise NotImplementedError


def legacy_parse(
    case: Case,
    text: str,
    evidence_ids: list[str],
    action_id: str | None = None,
    status: ReplyStatus | None = None,
) -> list[Action]:
    """TEMPORARY Phase 0 behaviour kept until the service uses `parse` + `apply` (Phase 4)."""
    actions = [a.model_copy(deep=True) for a in case.actions]
    if action_id is not None:
        target = next((a for a in actions if a.id == action_id), None)
        if target is None:
            raise InvalidActionError(f"unknown action: {action_id}")
        if target.status != ActionStatus.OPEN:
            raise InvalidActionError(f"action is not open: {action_id}")
    else:
        open_actions = [a for a in actions if a.status == ActionStatus.OPEN]
        if not open_actions:
            return actions
        target = open_actions[0]

    if status in ("skipped", "impossible"):
        target.status = ActionStatus(status)
        target.outcome = "neutral"
    else:
        target.status = ActionStatus.DONE
        target.outcome = keyword_outcome(text)
    target.answer = text
    target.answer_evidence_ids = list(evidence_ids)
    return actions
