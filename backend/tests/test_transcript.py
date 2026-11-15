from pathlib import Path

from app.contracts import Case, EvidenceKind
from app.intake.service import ingest
from app.intake.transcript import parse_transcript

CHAT = (
    "Alex Reed: Can I view the flat before sending the deposit?\n"
    "Rowan Pike: Transfer it now. I will not arrange a viewing until you pay.\n"
    "Account details:\n"
    "Sort code: 12-34-56\n"
    "Alex Reed: I need time to check.\n"
    "Rowan Pike: You have until 18:00.\n"
)


def test_name_colon_lines_become_messages_with_sides() -> None:
    messages = parse_transcript(CHAT, "ev_1", "Alex")
    assert [m.sender for m in messages] == ["student", "agent", "student", "agent"]
    assert messages[1].text == (
        "Transfer it now. I will not arrange a viewing until you pay.\n"
        "Account details:\nSort code: 12-34-56"
    )
    assert messages[3].text == "You have until 18:00."
    assert all(m.channel == "other" and m.evidence_id == "ev_1" for m in messages)


def test_whatsapp_web_copy_prefix_and_me_label() -> None:
    text = "[14:02, 14/11/2026] Me: is it still available?\n[14:03, 14/11/2026] Mark Evans: yes"
    messages = parse_transcript(text, "ev", None)
    assert [(m.sender, m.text) for m in messages] == [
        ("student", "is it still available?"),
        ("agent", "yes"),
    ]


def test_unknown_student_makes_everyone_the_agent() -> None:
    assert {m.sender for m in parse_transcript(CHAT, "ev", None)} == {"agent"}


def test_prose_and_single_speaker_text_are_not_transcripts() -> None:
    assert parse_transcript("", "ev", "Sam") == []
    assert parse_transcript("just some pasted words\nacross lines", "ev", "Sam") == []
    assert parse_transcript("Subject: the flat\nHello, please pay today.", "ev", "Sam") == []
    assert parse_transcript("Mark: pay now\nMark: today please", "ev", "Sam") == []
    assert parse_transcript("See https://example.com/a: b\nNote: c", "ev", "Sam") == []


async def test_pasted_chat_is_split_at_intake(tmp_path: Path) -> None:
    case = Case.model_validate({"case_id": "c1", "created_at": "2026-11-15T00:00:00Z"})
    case = await ingest(
        case, EvidenceKind.CHAT_EXPORT, None, CHAT.encode(), None, "Alex Reed", uploads_dir=tmp_path
    )
    assert [m.sender for m in case.messages] == ["student", "agent", "student", "agent"]
