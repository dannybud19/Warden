"""Pure helpers that build round notes and the composer's input."""

from datetime import UTC, datetime

from app.contracts import (
    Action,
    ActionKind,
    ActionStatus,
    AgentReport,
    AgentStatus,
    Case,
    Category,
    ChatTurn,
    Check,
    CheckId,
    CheckState,
    Evidence,
    EvidenceKind,
    EvidenceRef,
    Finding,
    ScoreResult,
    Severity,
)
from app.orchestrator import rounds
from app.orchestrator.composer import CheckMove, RoundNote
from app.orchestrator.conversation import ActionUpdate, ParseResult


def _update(outcome: str = "neutral", quote: str = "", action_id: str = "a1") -> ActionUpdate:
    return ActionUpdate(action_id, "done", outcome, quote)  # type: ignore[arg-type]


def _kinds(notes: list[RoundNote]) -> list[str]:
    return [n.kind for n in notes]


def test_reply_notes_unmatched_and_dropped() -> None:
    result = ParseResult(unmatched=True, used_fallback=True)  # the fallback itself is only logged
    assert _kinds(rounds.reply_notes(result, [], "ok")) == ["unmatched"]
    dropped = ParseResult(updates=(_update(),))
    assert _kinds(rounds.reply_notes(dropped, ["a1"], "yes")) == ["dropped"]


def test_upload_hint_only_for_a_flagged_payment_answer() -> None:
    flagged = ParseResult(updates=(_update("flags", "asked me to pay first"),))
    assert _kinds(rounds.reply_notes(flagged, [], "x")) == ["upload_hint"]
    # The keyword fallback has no quote: the reply text is read instead.
    fallback = ParseResult(updates=(_update("flags"),), used_fallback=True)
    assert "upload_hint" in _kinds(rounds.reply_notes(fallback, [], "No, bank transfer only"))
    viewing = ParseResult(updates=(_update("flags", "they refused a viewing"),))
    assert rounds.reply_notes(viewing, [], "x") == []
    cleared = ParseResult(updates=(_update("clears", "I paid by card after the viewing"),))
    assert rounds.reply_notes(cleared, [], "x") == []
    closed = ParseResult(updates=(_update("flags", "pay first"),))
    assert _kinds(rounds.reply_notes(closed, ["a1"], "x")) == ["dropped"]


def test_moved_checks_lists_only_changes() -> None:
    before = {
        CheckId.LANDLORD_IDENTITY: CheckState.UNVERIFIED,
        CheckId.FAIR_PRICE: CheckState.UNVERIFIED,
    }
    after = [
        Check(id=CheckId.LANDLORD_IDENTITY, state=CheckState.CLEARED),
        Check(id=CheckId.FAIR_PRICE),
    ]
    assert rounds.moved_checks(before, after) == [
        CheckMove(check="landlord identity", before="unverified", after="cleared")
    ]


def test_not_run_reports_errors_and_not_run_notes() -> None:
    note = Finding(
        id="companies_house:not-run-reputation",
        agent="companies_house",
        check_id=CheckId.LANDLORD_IDENTITY,
        title="Reputation check did not run",
        detail="search was down",
        category=Category.IDENTITY,
        severity=Severity.INFO,
        confidence=0.0,
    )
    reports = {
        "companies_house": AgentReport(
            agent="companies_house",
            version="1",
            status=AgentStatus.OK,
            input_hash="h",
            findings=[note],
        ),
        "message_checker": AgentReport(
            agent="message_checker", version="1", status=AgentStatus.ERROR, input_hash="h"
        ),
    }
    assert rounds.not_run(reports) == [
        "Reputation check did not run",
        "message_checker did not finish",
    ]


def test_changed_recap() -> None:
    assert rounds.changed_recap(None, "Two sources disagree on the rent.") is not None
    assert rounds.changed_recap("same", "same") is None
    assert rounds.changed_recap("old", None) is None
    assert rounds.changed_recap("old", "") is None


def test_round_input_counts_and_rounds_scores() -> None:
    at = datetime(2026, 11, 14, tzinfo=UTC)
    open_action = Action(
        id="a1", check_id=CheckId.IN_PERSON_VIEWING, kind=ActionKind.ACTION, text="Book a viewing"
    )
    done = open_action.model_copy(update={"id": "a0", "status": ActionStatus.DONE})
    inp = rounds.round_input(
        score_before=ScoreResult(at=at, score=100.0, contributions={}),
        score_after=ScoreResult(at=at, score=81.6, contributions={}),
        states_before={},
        checks_after=[],
        new_reports={},
        fresh=[open_action],
        actions=[done, open_action],
        recap_sent=True,
        notes=[RoundNote(kind="dropped")],
    )
    assert (inp.score_before, inp.score_after) == (100, 82)
    assert (inp.new_actions, inp.open_actions, inp.recap_sent) == (1, 1, True)
    assert inp.notes == (RoundNote(kind="dropped"),)


def _rent_case() -> Case:
    at = datetime(2026, 11, 14, tzinfo=UTC)
    rent = Finding(
        id="crosscheck:rent_pcm",
        agent="crosscheck",
        check_id=CheckId.CONTRACT_CONSISTENCY,
        title="Rent differs between sources",
        detail="'850' (from listing); '950' (from ev_c1)",
        category=Category.CONSISTENCY,
        severity=Severity.HIGH,
        confidence=0.9,
        evidence=[EvidenceRef(evidence_id="ev_c1", quote="950")],
    )
    minor = rent.model_copy(
        update={"id": "x:minor", "title": "Minor thing", "severity": Severity.MEDIUM}
    )
    report = AgentReport(
        agent="crosscheck",
        version="1",
        status=AgentStatus.OK,
        input_hash="h",
        findings=[minor, rent],
    )
    return Case(
        case_id="c",
        created_at=at,
        evidence=[Evidence(id="ev_c1", kind=EvidenceKind.CONTRACT, uploaded_at=at)],
        checks=[Check(id=CheckId.CONTRACT_CONSISTENCY, state=CheckState.SUSPICIOUS)],
        reports={"crosscheck": report},
        chat=[
            ChatTurn(role="orchestrator", text="Two sources disagree on the rent.", at=at),
            ChatTurn(role="student", text="how do they disagree", at=at),
        ],
    )


def test_grounding_gives_finding_detail_in_plain_words_most_serious_first() -> None:
    lines = rounds.grounding(_rent_case())
    assert lines[0] == (
        "Rent differs between sources: '850' (from listing); '950' (from the contract)"
    )
    assert lines[1].startswith("Minor thing")
    assert "contract consistency: suspicious" in lines


def test_history_lets_a_follow_up_question_see_the_last_turns() -> None:
    assert rounds.history(_rent_case()) == [
        "you: Two sources disagree on the rent.",
        "student: how do they disagree",
    ]


def test_round_input_always_sends_history_and_grounding_only_with_a_question() -> None:
    at = datetime(2026, 11, 14, tzinfo=UTC)
    common = {
        "score_before": None,
        "score_after": ScoreResult(at=at, score=80.0, contributions={}),
        "states_before": {},
        "checks_after": [],
        "new_reports": {},
        "fresh": [],
        "actions": [],
        "recap_sent": False,
        "case_grounding": ["g"],
        "case_history": ["student: hi"],
    }
    asked = rounds.round_input(**common, notes=[RoundNote(kind="question", text="how?")])
    assert (asked.history, asked.grounding) == (("student: hi",), ("g",))
    told = rounds.round_input(**common, notes=[])
    assert (told.history, told.grounding) == (("student: hi",), ())


def _finding(agent: str, slug: str, title: str, severity: Severity, supports: str) -> Finding:
    return Finding(
        id=f"{agent}:{slug}",
        agent=agent,
        check_id=CheckId.PAYMENT_SAFETY,
        title=title,
        detail="d",
        category=Category.PAYMENT,
        severity=severity,
        confidence=0.9,
        supports=supports,  # type: ignore[arg-type]
    )


def _report(agent: str, *findings: Finding, status: AgentStatus = AgentStatus.OK) -> AgentReport:
    return AgentReport(
        agent=agent, version="1", status=status, input_hash="h", findings=list(findings)
    )


def test_checked_lines_say_what_was_read_and_found() -> None:
    """A contract upload that moves no check must still tell the student it was read."""
    pay = _finding("message_checker", "pay", "Money requested early", Severity.HIGH, "suspicious")
    info = _finding("contract_checker", "cap", "Deposit within cap", Severity.LOW, "suspicious")
    new = {
        "contract_checker": _report("contract_checker", info),
        "message_checker": _report("message_checker", pay),
        "video_analysis": _report("video_analysis", status=AgentStatus.SKIPPED),
    }
    assert rounds.checked_lines(new, {}) == [
        "your messages: flagged: Money requested early",
        "the contract: nothing flagged",
    ]


def test_checked_lines_skip_a_rerun_that_found_the_same_and_unsayable_titles() -> None:
    pay = _finding("message_checker", "pay", "Money requested early", Severity.HIGH, "suspicious")
    scam = _finding("message_checker", "s", "Known scam wording", Severity.HIGH, "suspicious")
    same = {"message_checker": _report("message_checker", pay)}
    assert rounds.checked_lines(same, same) == []
    # A title the round message may not repeat ("scam") is never quoted.
    lines = rounds.checked_lines({"message_checker": _report("message_checker", scam, pay)}, {})
    assert lines == ["your messages: flagged: Money requested early"]


def test_reply_notes_say_how_each_answer_was_recorded() -> None:
    result = ParseResult(
        updates=(
            _update("clears", action_id="a1"),
            ActionUpdate("a2", "skipped", "neutral"),
            _update("flags", action_id="a3"),
        )
    )
    checks = {"a1": CheckId.IN_PERSON_VIEWING, "a2": CheckId.PAYMENT_SAFETY}
    notes = rounds.reply_notes(result, [], "I viewed it", checks)
    assert [(n.kind, n.text) for n in notes] == [
        ("answered", "in person viewing: you confirmed it, counted in your favour"),
        ("answered", "payment safety: skipped"),
    ]
