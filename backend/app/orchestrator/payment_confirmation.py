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
    """Bind answers to the finding and its quoted evidence, not just its reusable rule id."""
    payload = [finding.id, sorted((ref.evidence_id, ref.quote) for ref in finding.evidence)]
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:16]
    return f"{PREFIX}{digest}_"


def confirmed(case: Case, finding: Finding) -> bool:
    """Only an explicit yes to a question about this exact evidence confirms the concern."""
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
    """The student has replied to (or skipped) a confirmation about this exact evidence."""
    prefix = action_prefix(finding)
    return any(
        action.id.startswith(prefix) and action.status != ActionStatus.OPEN
        for action in case.actions
    )


def awaiting(case: Case) -> list[Finding]:
    """Pending concerns the student has not answered yet: only these hold up the next steps.

    A no, unsure, longer answer or skip keeps the concern (payment safety stays suspicious and
    the case cannot close on it) but is not asked again, so the conversation moves on instead
    of repeating the same question. New evidence for the concern is a new finding and is asked.
    """
    return [finding for finding in pending(case) if not answered(case, finding)]


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
        if finding.id == "message_checker:payment_before_viewing":
            ask = "Are they requiring payment before you or someone you trust can view in person?"
        elif finding.id == "message_checker:untraceable_payment":
            ask = "Are they asking you to pay using the method described in these messages?"
        else:
            ask = "Are they requiring payment under the conditions described in this warning?"
        quotes = " / ".join(f"“{ref.quote}”" for ref in finding.evidence)
        proposed.append(
            Action(
                id=f"{prefix}1",
                check_id=CheckId.PAYMENT_SAFETY,
                kind=ActionKind.QUESTION,
                text=(
                    "Please confirm this payment concern before we reach a decision. "
                    f"{finding.title}: {quotes} {ask} Reply yes, no, or unsure."
                ),
            )
        )
        if len(proposed) == limit:
            break
    return proposed
