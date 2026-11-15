"""WhatsApp .zip export reader."""

import io
import zipfile

import pytest

from app.intake import ocr, whatsapp, zip_export

LINE = "[15/11/2026, 14:02] Mark Evans: Deposit first please"


def make_zip(members: dict[str, bytes | str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def assert_zip_error(data: bytes) -> None:
    with pytest.raises(ocr.OCRError) as caught:
        zip_export.read_zip_export(data)
    assert caught.value.reason == ocr.ZIP


def test_is_zip() -> None:
    assert zip_export.is_zip(make_zip({"a.txt": "x"}))
    assert not zip_export.is_zip(b"%PDF-1.7")


def test_o16_reads_chat_txt_and_it_parses_like_an_export() -> None:
    data = make_zip({"_chat.txt": f"﻿{LINE}\n", "IMG-0001.jpg": b"\xff\xd8\xff" + b"\x00" * 64})
    text = zip_export.read_zip_export(data)
    assert text.startswith("[15/11/2026")  # BOM stripped
    messages = whatsapp.parse_export(text, "ev_1", "Sam")
    assert [m.text for m in messages] == ["Deposit first please"]
    assert messages[0].sender == "agent"


def test_single_txt_with_another_name_is_used() -> None:
    data = make_zip({"WhatsApp Chat with Mark Evans.txt": LINE, "PTT-0001.opus": b"\x00\x01"})
    assert zip_export.read_zip_export(data) == LINE


def test_chat_txt_wins_over_other_txt_and_macosx_is_ignored() -> None:
    data = make_zip(
        {"notes.txt": "other", "folder/_chat.txt": LINE, "__MACOSX/._chat.txt": b"junk"}
    )
    assert zip_export.read_zip_export(data) == LINE


def test_macosx_files_do_not_count_as_a_second_txt() -> None:
    data = make_zip({"chat.txt": LINE, "__MACOSX/._chat.txt": b"junk"})
    assert zip_export.read_zip_export(data) == LINE


def test_o17_no_txt() -> None:
    assert_zip_error(make_zip({"IMG-0001.jpg": b"\xff\xd8\xff", "readme.md": "hi"}))


def test_o17_two_ambiguous_txts() -> None:
    assert_zip_error(make_zip({"a.txt": LINE, "b.txt": LINE}))


def test_o17_oversized_txt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(zip_export, "MAX_TEXT_BYTES", 100)
    assert_zip_error(make_zip({"_chat.txt": "x" * 101}))
    assert zip_export.read_zip_export(make_zip({"_chat.txt": "x" * 100})) == "x" * 100


def test_o17_header_that_lies_about_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """A header that understates the size is refused (by zipfile itself or by the read cap)."""
    monkeypatch.setattr(zip_export, "MAX_TEXT_BYTES", 100)
    real_pick = zip_export._pick_member

    def lying_pick(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
        info = real_pick(archive)
        info.file_size = 50
        return info

    monkeypatch.setattr(zip_export, "_pick_member", lying_pick)
    assert_zip_error(make_zip({"_chat.txt": "x" * 500}))


def test_o17_not_a_zip() -> None:
    assert_zip_error(b"PK\x03\x04 this is not really a zip")
    assert_zip_error(b"plain text")
    assert_zip_error(b"")
