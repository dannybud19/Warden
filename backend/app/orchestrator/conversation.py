"""Chat with the student. Phase 0 placeholder, replaced in WS A."""

import re

from app.contracts import Action, ActionStatus, Case

CLEARS = ("yes", "confirmed", "verified", "they did", "it is", "registered")
FLAGS = ("no", "refused", "won't", "wouldn't", "can't", "declined", "abroad")


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![\w']){re.escape(word)}(?![\w'])", text) is not None


def parse(case: Case, text: str, evidence_ids: list[str]) -> list[Action]:
    """Mark the oldest open action as answered. Keyword outcome until WS A ships the LLM version.

    Returns the full updated action list; the Case itself is not modified.
    """
    # TODO(Danny, WS A): LLM mapping of a free-text reply onto several actions.
    actions = [a.model_copy(deep=True) for a in case.actions]
    open_actions = [a for a in actions if a.status == ActionStatus.OPEN]
    if not open_actions:
        return actions
    target = open_actions[0]  # actions are stored oldest first

    lowered = text.lower().replace("’", "'")
    if any(_has_word(lowered, w) for w in FLAGS):
        outcome = "flags"
    elif any(_has_word(lowered, w) for w in CLEARS):
        outcome = "clears"
    else:
        outcome = "neutral"

    target.status = ActionStatus.DONE
    target.answer = text
    target.answer_evidence_ids = list(evidence_ids)
    target.outcome = outcome
    return actions
