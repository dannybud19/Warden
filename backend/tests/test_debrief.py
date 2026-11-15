"""The pure builders of the voice-call debrief (no I/O, no LLM)."""

from datetime import UTC, datetime, timedelta, timezone

from app.contracts import Action, ActionKind, ActionStatus, Case, CheckId, EvidenceKind
from app.orchestrator import debrief
from app.orchestrator.debrief import CallAnswer, CallDebrief, CallLine

T0 = datetime(2026, 11, 15, 3, 30, tzinfo=UTC)


def line(role: debrief.Role, text: str, minutes: int = 0) -> CallLine:
    return CallLine(role, text, T0 + timedelta(minutes=minutes))


LINES = (
    line("orchestrator", "Tell me what happened.", 0),
    line("student", "They asked for a deposit before the viewing.", 1),
    line("orchestrator", "Did you pay?", 2),
    line("student", "Not yet, they want it today.", 3),
)


def case_with(*actions: Action) -> Case:
    return Case(case_id="c1", created_at=T0, actions=list(actions))


def action(action_id: str, status: ActionStatus = ActionStatus.OPEN) -> Action:
    return Action(
        id=action_id,
        check_id=CheckId.IN_PERSON_VIEWING,
        kind=ActionKind.QUESTION,
        text="?",
        status=status,
    )


def test_masked_hides_a_bank_account_in_lines_and_answers_but_keeps_a_phone_number() -> None:
    call = CallDebrief(
        lines=(line("student", "my account is 12345678 sort code 12-34-56, call 07700 900123"),),
        answers=(CallAnswer("a1", "I paid into account 87654321"),),
    )
    result = debrief.masked(call)
    text = result.lines[0].text
    assert "12345678" not in text and "12-34-56" not in text
    assert "07700 900123" in text
    assert "87654321" not in result.answers[0].answer


def test_masked_strips_text_and_drops_blank_lines_and_blank_answers() -> None:
    call = CallDebrief(
        lines=(line("student", "  hello  "), line("student", "   "), line("orchestrator", "")),
        answers=(CallAnswer("a1", "  "), CallAnswer("a2", " yes ", "skipped")),
    )
    result = debrief.masked(call)
    assert [ln.text for ln in result.lines] == ["hello"]
    assert result.answers == (CallAnswer("a2", "yes", "skipped"),)


def test_masked_keeps_a_company_number_in_full() -> None:
    result = debrief.masked(CallDebrief(lines=(line("student", "company number 01680058"),)))
    assert result.lines[0].text == "company number 01680058"


def test_transcript_text_is_one_labelled_line_per_turn() -> None:
    assert debrief.transcript_text(LINES).splitlines() == [
        "[03:30] Warden: Tell me what happened.",
        "[03:31] You: They asked for a deposit before the viewing.",
        "[03:32] Warden: Did you pay?",
        "[03:33] You: Not yet, they want it today.",
    ]


def test_transcript_text_shows_times_in_utc() -> None:
    plus_two = timezone(timedelta(hours=2))
    stamped = CallLine("student", "hi", datetime(2026, 11, 15, 5, 45, tzinfo=plus_two))
    assert debrief.transcript_text([stamped]) == "[03:45] You: hi"


def test_student_text_joins_only_the_student_lines() -> None:
    assert debrief.student_text(LINES) == (
        "They asked for a deposit before the viewing.\nNot yet, they want it today."
    )


def test_student_text_is_empty_without_student_lines() -> None:
    assert debrief.student_text([line("orchestrator", "Hello")]) == ""


def test_student_text_keeps_the_end_when_longer_than_the_limit() -> None:
    lines = [line("student", "a" * 50), line("student", "b" * 50)]
    cut = debrief.student_text(lines, max_chars=60)
    assert len(cut) == 60 and cut.endswith("b" * 50) and cut.startswith("a" * 9 + "\n")


def test_student_text_defaults_to_the_parser_limit() -> None:
    lines = [line("student", "x" * 5000), line("student", "y" * 5000)]
    assert len(debrief.student_text(lines)) == debrief.PARSER_MAX_CHARS


def test_build_evidence_is_a_call_recording_holding_the_transcript() -> None:
    evidence = debrief.build_evidence("ev_1", LINES, T0)
    assert evidence.id == "ev_1" and evidence.kind == EvidenceKind.CALL_RECORDING
    assert evidence.filename is None and evidence.note == debrief.EVIDENCE_NOTE
    assert evidence.uploaded_at == T0
    assert evidence.extracted_text == debrief.transcript_text(LINES)


def test_build_messages_makes_one_student_call_message_per_student_line() -> None:
    messages = debrief.build_messages("ev_1", LINES)
    assert [m.text for m in messages] == [
        "They asked for a deposit before the viewing.",
        "Not yet, they want it today.",
    ]
    assert {m.sender for m in messages} == {"student"}
    assert {m.channel for m in messages} == {"call"}
    assert {m.evidence_id for m in messages} == {"ev_1"}
    assert [m.sent_at for m in messages] == [T0 + timedelta(minutes=1), T0 + timedelta(minutes=3)]
    assert len({m.id for m in messages}) == 2 and all(m.id.startswith("msg_") for m in messages)


def test_build_chat_turns_keeps_every_line_in_order_with_its_role_and_time() -> None:
    turns = debrief.build_chat_turns(LINES)
    assert [(t.role, t.text, t.at) for t in turns] == [(ln.role, ln.text, ln.at) for ln in LINES]
    assert all(t.action_ids == [] for t in turns)


def test_split_answers_keeps_open_actions_and_drops_unknown_closed_and_repeated() -> None:
    case = case_with(action("open1"), action("open2"), action("closed", ActionStatus.DONE))
    answers = [
        CallAnswer("open1", "first"),
        CallAnswer("closed", "late"),
        CallAnswer("nope", "who"),
        CallAnswer("open1", "again"),
        CallAnswer("open2", "second", "skipped"),
    ]
    kept, dropped = debrief.split_answers(case, answers)
    assert kept == [answers[0], answers[4]]
    assert dropped == ["closed", "nope", "open1"]


def test_summary_note_reports_counts_as_an_answered_note() -> None:
    note = debrief.summary_note(2, 1)
    assert note.kind == "answered" and note.text == "call debrief: 2 answers, 1 facts"
