"""Chat with the student. Phase 0 placeholder, replaced in WS A."""

import re
from typing import Literal

from app.contracts import Action, ActionStatus, Case
from app.orchestrator.payment_confirmation import PREFIX as PAYMENT_CONFIRMATION_PREFIX

CLEARS = ("yes", "confirmed", "verified", "they did", "it is", "registered")
FLAGS = ("no", "refused", "won't", "wouldn't", "can't", "declined", "abroad")


class InvalidActionError(ValueError):
    """The reply names an action that does not exist or is no longer open (HTTP 422)."""


ReplyStatus = Literal["done", "skipped", "impossible"]


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![\w']){re.escape(word)}(?![\w'])", text) is not None


def _keyword_outcome(text: str) -> Literal["clears", "flags", "neutral"]:
    lowered = text.lower().replace("\u2019", "'")
    if any(_has_word(lowered, w) for w in FLAGS):
        return "flags"
    if any(_has_word(lowered, w) for w in CLEARS):
        return "clears"
    return "neutral"


def parse(
    case: Case,
    text: str,
    evidence_ids: list[str],
    action_id: str | None = None,
    status: ReplyStatus | None = None,
) -> list[Action]:
    """Apply the student's reply to one action and return the full updated action list.

    With `action_id`, only that action changes (InvalidActionError if it is unknown or not open).
    `skipped` and `impossible` set that status with a neutral outcome and no keyword parsing;
    `done` or no status uses the keyword outcome. Without `action_id` (free chat) the oldest open
    action is marked done. The Case itself is not modified.
    """
    # TODO(Danny, WS A): LLM mapping of a free-text reply onto several actions.
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
        target = next(
            (a for a in open_actions if a.id.startswith(PAYMENT_CONFIRMATION_PREFIX)),
            open_actions[0],
        )

    if status in ("skipped", "impossible"):
        target.status = ActionStatus(status)
        target.outcome = "neutral"
    else:
        target.status = ActionStatus.DONE
        if target.id.startswith(PAYMENT_CONFIRMATION_PREFIX):
            # This question asks about a concern, so yes confirms a flag. A denial/uncertainty
            # must never clear the whole payment check or be inferred from loose keywords.
            answer = text.strip().lower().rstrip(".! ")
            target.outcome = "flags" if answer == "yes" else "neutral"
        else:
            target.outcome = _keyword_outcome(text)
    target.answer = text
    target.answer_evidence_ids = list(evidence_ids)
    return actions
