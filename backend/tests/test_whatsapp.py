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
