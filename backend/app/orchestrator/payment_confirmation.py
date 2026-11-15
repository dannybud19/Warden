"""Require a targeted student confirmation before a payment hard flag closes a case."""

import hashlib
import json

from app.contracts import Action, ActionKind, ActionStatus, Case, CheckId, CheckState, Finding

PREFIX = "act_confirm_payment_"


def payment_flags(case: Case) -> list[Finding]:
    """Current payment hard flags backed by an active suspicious check."""
    active = {
        fid
        for check in case.checks
        if check.id == CheckId.PAYMENT_SAFETY and check.state == CheckState.SUSPICIOUS
        for fid in check.finding_ids
    }
    return [
        finding
        for report in case.reports.values()
        for finding in report.findings
        if finding.hard_flag and finding.id in active and finding.check_id == CheckId.PAYMENT_SAFETY
    ]


def action_prefix(finding: Finding) -> str:
    """Bind answers to the finding id only, so one concern has one confirmation for good.

    A chat that arrives in parts keeps the same finding id while its quotes grow. Hashing the
    quotes too gave every new part a new digest: a second question, a second message, and the
    first one left open for ever. The quotes shown to the student are refreshed in place
    (`refresh`) and an answer to the concern carries over as its evidence grows.
    """
    digest = hashlib.sha256(json.dumps([finding.id]).encode()).hexdigest()[:16]
    return f"{PREFIX}{digest}_"


def confirmed(case: Case, finding: Finding) -> bool:
    """Only an explicit yes to the question about this concern confirms it (a later "yes" on the
    same finding still counts after its evidence grows)."""
    prefix = action_prefix(finding)
    return any(
        action.id.startswith(prefix)
        and action.check_id == CheckId.PAYMENT_SAFETY
        and action.status == ActionStatus.DONE
        and action.outcome == "flags"
        and (action.answer or "").strip().lower().rstrip(".! ") == "yes"
        for action in case.actions
    )


def pending(case: Case) -> list[Finding]:
    """Unconfirmed payment concerns, including ones denied, skipped or answered uncertainly.

    They never decide the case on their own (`decision.hard_flags` needs a confirmed one)."""
    return [finding for finding in payment_flags(case) if not confirmed(case, finding)]


def answered(case: Case, finding: Finding) -> bool:
    """The student has replied to (or skipped) the confirmation about this concern."""
    prefix = action_prefix(finding)
    return any(
        action.id.startswith(prefix) and action.status != ActionStatus.OPEN
        for action in case.actions
    )


def awaiting(case: Case) -> list[Finding]:
    """Pending concerns the student has not answered yet: only these hold up the next steps.

    A no, unsure, longer answer or skip keeps the concern (payment safety stays suspicious and
    the case cannot close on it) but is not asked again, so the conversation moves on instead
    of repeating the same question. More evidence for the same finding is not asked again; a
    different finding is.
    """
    return [finding for finding in pending(case) if not answered(case, finding)]


def _question_text(finding: Finding) -> str:
    """The confirmation question for a finding, quoting its current evidence."""
    if finding.id == "message_checker:payment_before_viewing":
        ask = "Are they requiring payment before you or someone you trust can view in person?"
    elif finding.id == "message_checker:untraceable_payment":
        ask = "Are they asking you to pay using the method described in these messages?"
    else:
        ask = "Are they requiring payment under the conditions described in this warning?"
    quotes = " / ".join(f"“{ref.quote}”" for ref in finding.evidence)
    return (
        "Please confirm this payment concern before we reach a decision. "
        f"{finding.title}: {quotes} {ask} Reply yes, no, or unsure."
    )


def refresh(case: Case) -> list[Action]:
    """The case's actions with every still-open confirmation showing its finding's current quotes.

    Evidence that arrives in parts changes a finding's quotes but not its id, so the one open
    card is updated in place instead of a second one being asked.
    """
    text = {action_prefix(f): _question_text(f) for f in payment_flags(case)}
    refreshed = []
    for action in case.actions:
        new = next((t for p, t in text.items() if action.id.startswith(p)), None)
        if action.status == ActionStatus.OPEN and new is not None and new != action.text:
            action = action.model_copy(update={"text": new})
        refreshed.append(action)
    return refreshed


def questions(case: Case, limit: int = 3) -> list[Action]:
    """Ask once about each unanswered payment concern, within the open-action limit, but always
    at least one.

    An unanswered concern holds up every other step, so it must be asked even when three steps
    are already open (the agency check proposes three as soon as a home is added). Waiting for
    room left the case with nothing asked and nothing said: the chat stopped replying.
    """
    limit = max(1, limit - sum(action.status == ActionStatus.OPEN for action in case.actions))
    proposed = []
    for finding in awaiting(case):
        prefix = action_prefix(finding)
        if any(a.id.startswith(prefix) for a in case.actions):
            continue  # already asked and still open
        proposed.append(
            Action(
                id=f"{prefix}1",
                check_id=CheckId.PAYMENT_SAFETY,
                kind=ActionKind.QUESTION,
                text=_question_text(finding),
            )
        )
        if len(proposed) == limit:
            break
    return proposed
