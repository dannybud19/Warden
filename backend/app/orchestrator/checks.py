"""Check tracker: findings and answers to check states."""

from app.contracts import (
    ActionStatus,
    Case,
    Check,
    CheckId,
    CheckState,
    Finding,
    Severity,
)

SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


def initial_checks() -> list[Check]:
    """All 8 checks, UNVERIFIED."""
    return [Check(id=c) for c in CheckId]


def update(case: Case, findings: list[Finding]) -> list[Check]:
    """Recompute every check from findings and answers. Suspicious always beats cleared."""
    updated: list[Check] = []
    for check in case.checks:
        related = [f for f in findings if f.check_id == check.id]
        suspicious = [
            f
            for f in related
            if f.supports == "suspicious"
            and SEVERITY_RANK[f.severity] >= SEVERITY_RANK[Severity.MEDIUM]
            and f.confidence >= 0.6
        ]
        clearing = [f for f in related if f.supports == "cleared"]
        answers = [
            a for a in case.actions if a.check_id == check.id and a.status == ActionStatus.DONE
        ]
        flagging_answers = [a for a in answers if a.outcome == "flags"]
        clearing_answers = [a for a in answers if a.outcome == "clears"]

        if suspicious or flagging_answers:
            worst = max(suspicious, key=lambda f: SEVERITY_RANK[f.severity], default=None)
            reason = worst.title if worst else f"Student reported: {flagging_answers[0].answer}"
            updated.append(
                check.model_copy(
                    update={
                        "state": CheckState.SUSPICIOUS,
                        "clear_confidence": 0.0,
                        "finding_ids": [f.id for f in suspicious],
                        "reason": reason,
                    }
                )
            )
        elif clearing or clearing_answers:
            confidences = [f.confidence for f in clearing] + [
                0.9 if a.answer_evidence_ids else 0.7 for a in clearing_answers
            ]
            updated.append(
                check.model_copy(
                    update={
                        "state": CheckState.CLEARED,
                        "clear_confidence": max(confidences),
                        "finding_ids": [f.id for f in clearing],
                        "reason": clearing[0].title if clearing else "Confirmed by the student",
                    }
                )
            )
        else:
            updated.append(
                check.model_copy(
                    update={
                        "state": CheckState.UNVERIFIED,
                        "clear_confidence": 0.0,
                        "finding_ids": [],
                        "reason": None,
                    }
                )
            )
    return updated
