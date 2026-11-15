from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.contracts import Case, EvidenceKind
from app.intake.redact import mask_sensitive
from app.intake.service import ingest


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("sort code 12-34-56, account 00001234.", "sort code **-**-56, account ****1234."),
        ("Sort code: 123456 acc 87654321", "Sort code: **-**-56 acc ****4321"),
        ("sort 12 34 56", "sort **-**-56"),
        ("IBAN DE89 3704 0044 0532 0130 00 please", "IBAN DE** **** **** 3000 please"),
        ("GB29NWBK60161331926819", "GB** **** **** 6819"),
        ("card 4111 1111 1111 1111", "card **** **** **** 1111"),
        ("a/c 87654321 at the bank", "a/c ****4321 at the bank"),
        ("12-34-56 00001234", "**-**-56 ****1234"),
        ("Bank transfer: 00001234 (Mark Evans)", "Bank transfer: ****1234 (Mark Evans)"),
        ("reference 123456789012", "reference ****9012"),
        (
            "call 07700 900123 then pay account 00001234",
            "call 07700 900123 then pay account ****1234",
        ),
    ],
)
def test_financial_identifiers_are_masked(text: str, masked: str) -> None:
    assert mask_sensitive(text) == masked


@pytest.mark.parametrize(
    "text",
    [
        "£850 pcm, bills included. Deposit £1,200.00",
        "[12/11/2026, 18:02:11] Mark: available from 1 December 2026",
        "Flat 3, 12 Elm Road, London W12 8QT",
        "Company number 12345678",
        "Prime City Lettings Ltd (registered no. 09876543)",
        "CRN: 01234567",
        "Companies House: 11223344",
        "SC123456",
        # Bare 8-digit numbers with no bank wording near them: company numbers (Danny, PR #1).
        "Prime City Lettings Ltd 09876543",
        "We are registered in England, 12345678.",
        "our number is 01234567",
    ],
)
def test_ordinary_and_public_text_is_kept(text: str) -> None:
    assert mask_sensitive(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "call 07700 900123",
        "call 07700900123 today",
        "WhatsApp me on +44 7700 900123",
        "+447700900123",
        "+44 (0)20 7946 0958",
        "0044 7700 900 123",
        "Office: 020 7946 0958.",
        "(020) 7946 0958",
        "0161 496 0123",
        "01632 960123",
        "0800 123 4567",
        "07700-900-123",
        "email mark@primecity-lettings.co.uk or ring 07700 900123",
    ],
)
def test_phone_numbers_and_emails_are_kept(text: str) -> None:
    """The Companies House contact check needs the full phone number and the email domain."""
    assert mask_sensitive(text) == text


def test_masking_is_idempotent() -> None:
    once = mask_sensitive("sort code 12-34-56, account 00001234, IBAN DE89370400440532013000")
    assert mask_sensitive(once) == once


def _files(folder: Path, pattern: str = "*") -> list[Path]:
    return [p for p in folder.rglob(pattern) if p.is_file()]


async def test_ingest_masks_text_and_messages_and_skips_raw_file(tmp_path: Path) -> None:
    case = Case(case_id="c1", created_at=datetime.now(UTC))
    chat = (
        b"[12/11/2026, 18:14:30] Mark: Bank transfer to Prime City Lettings Ltd, "
        b"sort code 12-34-56, account 00001234.\n"
    )
    out = await ingest(
        case,
        EvidenceKind.CHAT_EXPORT,
        "chat.txt",
        chat,
        "account 00001234",
        "Sam",
        uploads_dir=tmp_path,
    )
    evidence = out.evidence[0]
    stored = [evidence.extracted_text or "", evidence.note or "", *(m.text for m in out.messages)]
    assert out.messages and all("00001234" not in t and "12-34-56" not in t for t in stored)
    assert "sort code **-**-56, account ****1234" in out.messages[0].text
    assert evidence.file_url is None and not _files(tmp_path)


async def test_ingest_keeps_raw_file_when_no_text_is_extracted(tmp_path: Path) -> None:
    case = Case(case_id="c1", created_at=datetime.now(UTC))
    out = await ingest(
        case, EvidenceKind.VIDEO, "tour.mp4", b"\x00", None, None, uploads_dir=tmp_path
    )
    assert out.evidence[0].file_url and _files(tmp_path, "*tour.mp4")
