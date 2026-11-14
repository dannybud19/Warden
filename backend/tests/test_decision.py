from datetime import UTC, datetime

from app.contracts import (
    AgentReport,
    AgentStatus,
    Case,
    Category,
    Check,
    CheckId,
    CheckState,
    Finding,
    Severity,
    Verdict,
)
from app.orchestrator.checks import initial_checks
from app.orchestrator.decision import CHECK_QUESTIONS, decide

CORE = [CheckId.LANDLORD_IDENTITY, CheckId.PAYMENT_SAFETY, CheckId.RIGHT_TO_LET]


def _case(states: dict[CheckId, CheckState], *, findings: list[Finding] | None = None) -> Case:
    checks: list[Check] = []
    for check in initial_checks():
        state = states.get(check.id, CheckState.UNVERIFIED)
        ids = [f.id for f in (findings or []) if f.check_id == check.id]
        checks.append(
            check.model_copy(
                update={
                    "state": state,
                    "clear_confidence": 0.9 if state == CheckState.CLEARED else 0.0,
                    "reason": f"{check.id.value} reason"
                    if state == CheckState.SUSPICIOUS
                    else None,
                    "finding_ids": ids if state == CheckState.SUSPICIOUS else [],
                }
            )
        )
    reports = {}
    if findings:
        reports["t"] = AgentReport(
            agent="t", version="t", status=AgentStatus.OK, input_hash="", findings=findings
        )
    return Case(
        case_id="c",
        created_at=datetime(2026, 11, 14, 15, tzinfo=UTC),
        checks=checks,
        reports=reports,
    )


def _hard_finding(check: CheckId) -> Finding:
    return Finding(
        id="t:hard",
        agent="t",
        check_id=check,
        title="t",
        detail="d",
        category=Category.PAYMENT,
        severity=Severity.CRITICAL,
        confidence=0.9,
        hard_flag=True,
    )


def test_non_payment_hard_flag_means_likely_scam() -> None:
    finding = _hard_finding(CheckId.LANDLORD_IDENTITY)
    case = _case({CheckId.LANDLORD_IDENTITY: CheckState.SUSPICIOUS}, findings=[finding])
    decision = decide(case)
    assert decision.verdict == Verdict.LIKELY_SCAM
    assert "t:hard" in decision.finding_ids


def test_payment_candidate_cannot_bypass_confirmation_via_two_core_checks() -> None:
    finding = _hard_finding(CheckId.PAYMENT_SAFETY)
    case = _case(
        {
            CheckId.PAYMENT_SAFETY: CheckState.SUSPICIOUS,
            CheckId.LANDLORD_IDENTITY: CheckState.SUSPICIOUS,
        },
        findings=[finding],
    )
    assert decide(case).verdict == Verdict.NOT_VERIFIED


def test_two_core_suspicious_means_likely_scam() -> None:
    case = _case(
        {
            CheckId.LANDLORD_IDENTITY: CheckState.SUSPICIOUS,
            CheckId.RIGHT_TO_LET: CheckState.SUSPICIOUS,
        }
    )
    assert decide(case).verdict == Verdict.LIKELY_SCAM


def test_one_core_suspicious_is_not_verified() -> None:
    case = _case(
        {
            CheckId.LANDLORD_IDENTITY: CheckState.SUSPICIOUS,
            CheckId.PAYMENT_SAFETY: CheckState.CLEARED,
            CheckId.RIGHT_TO_LET: CheckState.CLEARED,
        }
    )
    assert decide(case).verdict == Verdict.NOT_VERIFIED


def test_core_not_cleared_is_not_verified_with_reasons() -> None:
    case = _case({CheckId.LANDLORD_IDENTITY: CheckState.CLEARED})
    decision = decide(case)
    assert decision.verdict == Verdict.NOT_VERIFIED
    assert decision.reasons == [
        f"Not yet verified: {CHECK_QUESTIONS[CheckId.PAYMENT_SAFETY]}",
        f"Not yet verified: {CHECK_QUESTIONS[CheckId.RIGHT_TO_LET]}",
    ]


def test_core_cleared_but_other_not_is_proceed_with_care() -> None:
    case = _case({c: CheckState.CLEARED for c in CORE})
    decision = decide(case)
    assert decision.verdict == Verdict.PROCEED_WITH_CARE
    assert decision.reasons == []


def test_everything_cleared_is_no_red_flags_and_never_safe() -> None:
    case = _case({c.id: CheckState.CLEARED for c in initial_checks()})
    decision = decide(case)
    assert decision.verdict == Verdict.NO_RED_FLAGS
    assert "safe" not in decision.summary.lower()


def test_summary_and_reasons_for_suspicious_checks() -> None:
    case = _case(
        {
            CheckId.PAYMENT_SAFETY: CheckState.SUSPICIOUS,
            CheckId.NO_PRESSURE: CheckState.SUSPICIOUS,
        }
    )
    decision = decide(case)
    assert decision.summary.startswith("2 of 8 checks are suspicious, including payment safety")
    assert decision.reasons[:2] == ["payment_safety reason", "no_pressure reason"]


def test_unconfirmed_hard_flag_is_not_enough() -> None:
    """A hard-flag finding outside a SUSPICIOUS check does not close the case."""
    case = _case({}, findings=[_hard_finding(CheckId.PAYMENT_SAFETY)])
    assert decide(case).verdict == Verdict.NOT_VERIFIED
