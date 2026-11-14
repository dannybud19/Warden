from datetime import UTC, datetime

from app.contracts import (
    Action,
    ActionKind,
    ActionStatus,
    Case,
    Category,
    CheckId,
    CheckState,
    EvidenceRef,
    Finding,
    Severity,
)
from app.orchestrator.checks import initial_checks, update


def _finding(
    check: CheckId,
    *,
    supports: str = "suspicious",
    severity: Severity = Severity.HIGH,
    confidence: float = 0.9,
    slug: str = "f",
) -> Finding:
    return Finding(
        id=f"t:{slug}",
        agent="t",
        check_id=check,
        title=f"title {slug}",
        detail="d",
        category=Category.IDENTITY,
        severity=severity,
        confidence=confidence,
        evidence=[EvidenceRef(evidence_id="ev", quote="q")],
        supports=supports,  # type: ignore[arg-type]
    )


def _case(actions: list[Action] | None = None) -> Case:
    return Case(
        case_id="c",
        created_at=datetime(2026, 11, 14, 15, tzinfo=UTC),
        checks=initial_checks(),
        actions=actions or [],
    )


def _state(case: Case, findings: list[Finding], check: CheckId):
    return next(c for c in update(case, findings) if c.id == check)


def test_initial_checks_are_all_unverified() -> None:
    checks = initial_checks()
    assert len(checks) == 8 and all(c.state == CheckState.UNVERIFIED for c in checks)


def test_suspicious_beats_cleared() -> None:
    check = _state(
        _case(),
        [
            _finding(CheckId.LANDLORD_IDENTITY, slug="bad"),
            _finding(CheckId.LANDLORD_IDENTITY, supports="cleared", slug="good"),
        ],
        CheckId.LANDLORD_IDENTITY,
    )
    assert check.state == CheckState.SUSPICIOUS
    assert check.finding_ids == ["t:bad"] and check.reason == "title bad"


def test_weak_or_low_findings_do_not_make_a_check_suspicious() -> None:
    findings = [
        _finding(CheckId.NO_PRESSURE, severity=Severity.LOW, slug="low"),
        _finding(CheckId.FAIR_PRICE, confidence=0.5, slug="unsure"),
    ]
    case = _case()
    assert _state(case, findings, CheckId.NO_PRESSURE).state == CheckState.UNVERIFIED
    assert _state(case, findings, CheckId.FAIR_PRICE).state == CheckState.UNVERIFIED


def test_clearing_finding_clears_with_its_confidence() -> None:
    check = _state(
        _case(),
        [_finding(CheckId.LANDLORD_IDENTITY, supports="cleared", confidence=0.8)],
        CheckId.LANDLORD_IDENTITY,
    )
    assert check.state == CheckState.CLEARED and check.clear_confidence == 0.8


def _answer(outcome: str, evidence_ids: list[str] | None = None) -> Action:
    return Action(
        id="act_x",
        check_id=CheckId.PAYMENT_SAFETY,
        kind=ActionKind.QUESTION,
        text="?",
        status=ActionStatus.DONE,
        answer="the answer",
        answer_evidence_ids=evidence_ids or [],
        outcome=outcome,  # type: ignore[arg-type]
    )


def test_clearing_answer_with_evidence_gives_confidence_0_9() -> None:
    check = _state(_case([_answer("clears", ["ev_1"])]), [], CheckId.PAYMENT_SAFETY)
    assert check.state == CheckState.CLEARED and check.clear_confidence == 0.9
    assert check.reason == "Confirmed by the student"


def test_clearing_answer_without_evidence_gives_confidence_0_7() -> None:
    check = _state(_case([_answer("clears")]), [], CheckId.PAYMENT_SAFETY)
    assert check.clear_confidence == 0.7


def test_flagging_answer_makes_the_check_suspicious() -> None:
    check = _state(_case([_answer("flags")]), [], CheckId.PAYMENT_SAFETY)
    assert check.state == CheckState.SUSPICIOUS
    assert check.reason == "Student reported: the answer"


def test_neutral_answer_changes_nothing() -> None:
    assert _state(_case([_answer("neutral")]), [], CheckId.PAYMENT_SAFETY).state == (
        CheckState.UNVERIFIED
    )


def test_open_actions_are_ignored() -> None:
    open_action = _answer("clears").model_copy(update={"status": ActionStatus.OPEN})
    assert _state(_case([open_action]), [], CheckId.PAYMENT_SAFETY).state == CheckState.UNVERIFIED
