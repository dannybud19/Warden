from datetime import UTC, datetime
from pathlib import Path

from app.intake.whatsapp import parse_export

DATA = Path(__file__).parent / "data"


def _ios() -> str:
    # Real iOS exports put an invisible left-to-right mark (U+200E) before every line.
    lines = (DATA / "whatsapp_ios.txt").read_text().splitlines()
    return "\n".join("‎" + line for line in lines)


def test_ios_format_multiline_and_sender_mapping() -> None:
    messages = parse_export(_ios(), "ev_1", "sam")
    assert [m.sender for m in messages] == ["student", "agent", "student", "agent"]
    assert messages[0].text == "Hi Mark, is the flat still available?"
    assert messages[1].text == "Yes it is.\nRent is £850 pcm.\nBills included."
    assert messages[0].sent_at == datetime(2026, 11, 12, 18, 2, 11, tzinfo=UTC)
    assert all(m.channel == "whatsapp" and m.evidence_id == "ev_1" for m in messages)
    assert "‎" not in "".join(m.text for m in messages)


def test_ios_two_digit_year_and_system_lines_are_skipped() -> None:
    messages = parse_export(_ios(), "ev_1", "Sam")
    assert messages[2].sent_at == datetime(2026, 11, 12, 18, 6, 2, tzinfo=UTC)
    assert not any("end-to-end" in m.text or "created group" in m.text for m in messages)
    assert messages[3].text == "No, I'm abroad."


def test_android_format() -> None:
    messages = parse_export((DATA / "whatsapp_android.txt").read_text(), "ev_2", "Sam")
    assert [m.sender for m in messages] == ["student", "agent", "student", "agent"]
    assert messages[1].text == "Yes it is.\nRent is £850 pcm."
    assert messages[3].sent_at == datetime(2026, 11, 13, 9, 20, tzinfo=UTC)
    assert messages[3].text == "Send the deposit today."


def test_unknown_student_name_makes_everyone_the_agent() -> None:
    messages = parse_export((DATA / "whatsapp_android.txt").read_text(), "ev_2", None)
    assert {m.sender for m in messages} == {"agent"}


def test_empty_and_non_whatsapp_text_give_no_messages() -> None:
    assert parse_export("", "ev", "Sam") == []
    assert parse_export("just some pasted words\nacross lines", "ev", "Sam") == []


def _chat(*lines: str) -> str:
    return "\n".join(f"[12/11/2026, 18:0{i}:00] {line}" for i, line in enumerate(lines))


def test_first_name_matches_the_full_whatsapp_name() -> None:
    """The app may know only "Georgi" while the export says "Georgi Roussinov"."""
    text = _chat("Georgi Roussinov: Can I view it before the deposit?", "Mark Evans: Pay first.")
    senders = [m.sender for m in parse_export(text, "ev", "Georgi")]
    assert senders == ["student", "agent"]
    senders = [m.sender for m in parse_export(_chat("georgi: hi", "Mark: pay"), "ev", "Georgi R")]
    assert senders == ["student", "agent"]


def test_ambiguous_first_name_is_not_guessed() -> None:
    text = _chat("Sam Reed: Can I view it?", "Sam Pike: Pay the deposit first.")
    assert [m.sender for m in parse_export(text, "ev", "Sam")] == ["agent", "agent"]
    # an exact full name still decides
    assert [m.sender for m in parse_export(text, "ev", "sam  reed")] == ["student", "agent"]


def test_placeholder_name_matches_nobody() -> None:
    text = _chat("Sam: Can I view it?", "Mark: Pay first.")
    assert [m.sender for m in parse_export(text, "ev", "student")] == ["agent", "agent"]


def test_twelve_hour_clock_exports() -> None:
    """Phones on a 12-hour clock write "2:05:00 pm" (iOS uses a narrow no-break space)."""
    ios = "[12/11/2026, 6:02:11 PM] Sam: Hi\n[12/11/2026, 12:05:00 am] Mark Evans: Pay first."
    messages = parse_export(ios, "ev", "Sam")
    assert [m.sender for m in messages] == ["student", "agent"]
    assert messages[0].sent_at == datetime(2026, 11, 12, 18, 2, 11, tzinfo=UTC)
    assert messages[1].sent_at == datetime(2026, 11, 12, 0, 5, tzinfo=UTC)
    android = "12/11/2026, 9:20 pm - Mark Evans: Send the deposit today."
    sent = parse_export(android, "ev", "Sam")[0].sent_at
    assert sent == datetime(2026, 11, 12, 21, 20, tzinfo=UTC)
