"""Final decision rules. Pure: `decide(case) -> Decision`. Never calls anything "safe"."""

from datetime import UTC, datetime

from app.contracts import Case, CheckId, CheckState, Decision, Finding, Verdict
from app.orchestrator import payment_confirmation

CORE_CHECKS = (CheckId.LANDLORD_IDENTITY, CheckId.PAYMENT_SAFETY, CheckId.RIGHT_TO_LET)

# NOTE: wording is ours; the team doc's scoring table is not in the repo.
CHECK_QUESTIONS: dict[CheckId, str] = {
    CheckId.LANDLORD_IDENTITY: "Is the landlord or agency a real, registered business or person?",
    CheckId.PAYMENT_SAFETY: "Is every payment traceable, to the right party, and after a viewing?",
    CheckId.RIGHT_TO_LET: "Does the person have the legal right to let this property?",
    CheckId.IN_PERSON_VIEWING: "Has an in-person viewing happened, or been properly offered?",
    CheckId.CONTRACT_CONSISTENCY: "Do the contract and listing agree on address, rent and fees?",
    CheckId.DEPOSIT_PROTECTION: "Will the deposit be held in a government-approved scheme?",
    CheckId.NO_PRESSURE: "Are you free to decide without urgency or pressure?",
    CheckId.FAIR_PRICE: "Is the rent in line with similar properties nearby?",
}

_VERDICT_TEXT: dict[Verdict, str] = {
    Verdict.LIKELY_SCAM: "This looks like a likely scam. Do not send money or personal documents.",
    Verdict.NOT_VERIFIED: "Key checks are not verified yet. Do not pay anything until they are.",
    Verdict.PROCEED_WITH_CARE: "The key checks are clear, but others are not. Proceed with care.",
    Verdict.NO_RED_FLAGS: "No red flags remain. This is not a guarantee: keep checking as you go.",
}


def _label(check_id: CheckId) -> str:
    return check_id.value.replace("_", " ")


def _all_findings(case: Case) -> list[Finding]:
    return [f for report in case.reports.values() for f in report.findings]


def hard_flags(case: Case) -> list[Finding]:
    """Hard-flag findings that sit inside a SUSPICIOUS check (i.e. confirmed)."""
    suspicious_ids = {
        fid for c in case.checks if c.state == CheckState.SUSPICIOUS for fid in c.finding_ids
    }
    return [
        f
        for f in _all_findings(case)
        if f.hard_flag
        and f.id in suspicious_ids
        and (f.check_id != CheckId.PAYMENT_SAFETY or payment_confirmation.confirmed(case, f))
    ]


def decide(case: Case) -> Decision:
    """Apply the verdict table to the Case's checks and findings."""
    state = {c.id: c.state for c in case.checks}
    suspicious_checks = [c for c in case.checks if c.state == CheckState.SUSPICIOUS]
    suspicious_ids = {fid for c in suspicious_checks for fid in c.finding_ids}
    hard = hard_flags(case)
    core_suspicious = [c for c in CORE_CHECKS if state.get(c) == CheckState.SUSPICIOUS]
    core_not_cleared = [c for c in CORE_CHECKS if state.get(c) != CheckState.CLEARED]

    if hard or (len(core_suspicious) >= 2 and not payment_confirmation.pending(case)):
        verdict = Verdict.LIKELY_SCAM
    elif core_not_cleared:
        verdict = Verdict.NOT_VERIFIED
    elif any(c.state != CheckState.CLEARED for c in case.checks):
        verdict = Verdict.PROCEED_WITH_CARE
    else:
        verdict = Verdict.NO_RED_FLAGS

    named = ", ".join(_label(c.id) for c in suspicious_checks[:3])
    head = f"{len(suspicious_checks)} of {len(case.checks)} checks are suspicious"
    summary = f"{head}, including {named}. " if named else f"{head}. "
    summary += _VERDICT_TEXT[verdict]

    reasons = [c.reason for c in suspicious_checks if c.reason]
    reasons += [
        f"Not yet verified: {CHECK_QUESTIONS[c.id]}"
        for c in case.checks
        if c.id in CORE_CHECKS and c.state == CheckState.UNVERIFIED
    ]
    finding_ids = sorted(suspicious_ids | {f.id for f in hard})
    return Decision(
        verdict=verdict,
        decided_at=datetime.now(UTC),
        summary=summary,
        reasons=reasons,
        finding_ids=finding_ids,
    )
