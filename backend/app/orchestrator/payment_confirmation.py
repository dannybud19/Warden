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
    """Unconfirmed payment concerns, including ones denied, skipped or answered uncertainly."""
    return [finding for finding in payment_flags(case) if not confirmed(case, finding)]


def questions(case: Case, limit: int = 3) -> list[Action]:
    """Ask about missing confirmations; follow up on a denial without clearing payment safety."""
    limit -= sum(action.status == ActionStatus.OPEN for action in case.actions)
    if limit <= 0:
        return []
    proposed = []
    for finding in pending(case):
        prefix = action_prefix(finding)
        previous = [action for action in case.actions if action.id.startswith(prefix)]
        if any(action.status == ActionStatus.OPEN for action in previous):
            continue
        if finding.id == "message_checker:payment_before_viewing":
            ask = "Are they requiring payment before you or someone you trust can view in person?"
        elif finding.id == "message_checker:untraceable_payment":
            ask = "Are they asking you to pay using the method described in these messages?"
        else:
            ask = "Are they requiring payment under the conditions described in this warning?"
        quotes = " / ".join(f"“{ref.quote}”" for ref in finding.evidence)
        lead = (
            "The concern is unresolved. Please check the full messages or provide more context. "
            if previous
            else "Please confirm this payment concern before we reach a decision. "
        )
        proposed.append(
            Action(
                id=f"{prefix}{len(previous) + 1}",
                check_id=CheckId.PAYMENT_SAFETY,
                kind=ActionKind.QUESTION,
                text=f"{lead}{finding.title}: {quotes} {ask} Reply exactly yes, no, or unsure.",
            )
        )
        if len(proposed) == limit:
            break
    return proposed
