"""Image uploads through intake: routing by kind, dedupe of overlapping screenshots."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.contracts import Case, EvidenceKind
from app.core.llm import FakeLLM
from app.intake.service import attach, extract, ingest
from tests.test_intake_documents import _docx_bytes
from tests.test_service_ocr import PNG

HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32
IOS_LINE = "[12/11/2026, 18:05:40] Mark Evans: Yes it is available."


def _case() -> Case:
    return Case.model_validate({"case_id": "case_t", "created_at": datetime.now(UTC).isoformat()})


def _chat(*lines: tuple[str, str]) -> str:
    return json.dumps(
        {
            "is_chat": True,
            "app": "whatsapp",
            "other_party": "Mark Evans",
            "lines": [{"side": side, "time": "14:02", "text": text} for side, text in lines],
        }
    )


def _llm(chat: str | None = None, document: str | None = None) -> FakeLLM:
    responses: dict[str, str] = {}
    if chat is not None:
        responses["chat conversation"] = chat
    if document is not None:
        responses["of a document"] = json.dumps({"is_document": True, "text": document})
    return FakeLLM(responses)


def _vision_calls(llm: FakeLLM) -> list[dict[str, Any]]:
    return [c for c in llm.calls if c["method"] == "describe_image"]


async def test_contract_image_is_read_as_a_document(tmp_path: Path) -> None:  # O9
    for kind in (EvidenceKind.CONTRACT, EvidenceKind.DOCUMENT, EvidenceKind.LISTING):
        llm = _llm(document="Assured Shorthold Tenancy\nRent: £850 per month")
        case = await ingest(
            _case(), kind, "scan.png", PNG, None, "Sam", uploads_dir=tmp_path, llm=llm
        )
        assert case.evidence[-1].extracted_text == "Assured Shorthold Tenancy\nRent: £850 per month"
        assert case.messages == []
        assert len(_vision_calls(llm)) == 1


async def test_email_image_becomes_one_agent_email_message(tmp_path: Path) -> None:  # O10
    llm = _llm(document="Dear Sam, please pay the holding deposit today.")
    case = await ingest(
        _case(), EvidenceKind.EMAIL, "mail.png", PNG, None, "Sam", uploads_dir=tmp_path, llm=llm
    )
    assert len(case.messages) == 1
    message = case.messages[0]
    assert (message.channel, message.sender) == ("email", "agent")
    assert message.text == "Dear Sam, please pay the holding deposit today."
    assert case.evidence[-1].extracted_text == message.text


async def test_text_sent_as_a_screenshot_uses_the_whatsapp_parser(tmp_path: Path) -> None:  # O11
    llm = _llm(chat=_chat(("left", "should not be used")))
    case = await ingest(
        _case(),
        EvidenceKind.CHAT_SCREENSHOT,
        "chat.txt",
        IOS_LINE.encode(),
        None,
        "Sam",
        uploads_dir=tmp_path,
        llm=llm,
    )
    assert [(m.sender, m.text) for m in case.messages] == [("agent", "Yes it is available.")]
    assert llm.calls == []


async def test_overlapping_screenshots_add_only_the_new_messages(tmp_path: Path) -> None:  # O12
    first = _llm(chat=_chat(("left", "Hello Sam"), ("right", "Hi Mark"), ("left", "Pay today")))
    second = _llm(chat=_chat(("right", "  hi   MARK "), ("left", "Pay today"), ("left", "Hurry")))
    case = await ingest(
        _case(),
        EvidenceKind.CHAT_SCREENSHOT,
        "a.png",
        PNG,
        None,
        "Sam",
        uploads_dir=tmp_path,
        llm=first,
    )
    case = await ingest(
        case,
        EvidenceKind.CHAT_SCREENSHOT,
        "b.png",
        PNG,
        None,
        "Sam",
        uploads_dir=tmp_path,
        llm=second,
    )
    assert [m.text for m in case.messages] == ["Hello Sam", "Hi Mark", "Pay today", "Hurry"]
    # both evidences keep their full transcript
    assert "Hello Sam" in (case.evidence[0].extracted_text or "")
    assert "Pay today" in (case.evidence[1].extracted_text or "")
    assert "hi   MARK" in (case.evidence[1].extracted_text or "")


async def test_dedupe_ignores_messages_from_a_chat_export(tmp_path: Path) -> None:  # O12
    case = await ingest(
        _case(),
        EvidenceKind.CHAT_EXPORT,
        "chat.txt",
        IOS_LINE.encode(),
        None,
        "Sam",
        uploads_dir=tmp_path,
    )
    llm = _llm(chat=_chat(("left", "yes it is   available.")))
    case = await ingest(
        case,
        EvidenceKind.CHAT_SCREENSHOT,
        "s.png",
        PNG,
        None,
        "Sam",
        uploads_dir=tmp_path,
        llm=llm,
    )
    assert [m.text for m in case.messages].count("Yes it is available.") == 1
    assert len(case.messages) == 2  # the screenshot copy is kept: only screenshots dedupe


async def test_screenshot_without_an_llm_keeps_the_old_behaviour(tmp_path: Path) -> None:
    extracted = await extract(EvidenceKind.CHAT_SCREENSHOT, "c.png", PNG, "Sam", None)
    assert extracted.text is None
    assert extracted.messages == []
    assert extracted.error is None
    case = await attach(
        _case(), EvidenceKind.CHAT_SCREENSHOT, "c.png", PNG, None, extracted, uploads_dir=tmp_path
    )
    assert case.evidence[-1].extracted_text is None


async def test_docx_and_text_contracts_skip_the_vision_model() -> None:
    llm = _llm(document="from the vision model")
    word = await extract(EvidenceKind.CONTRACT, "c.docx", _docx_bytes(), "Sam", llm)
    plain = await extract(EvidenceKind.CONTRACT, "c.txt", b"Rent is 850", "Sam", llm)
    assert plain.text == "Rent is 850"
    assert word.text == "Assured Shorthold Tenancy\nRent: £850 per month\nDeposit\t£980"
    assert _vision_calls(llm) == []


async def test_unreadable_images_return_an_error_instead_of_raising() -> None:
    llm = _llm(chat=json.dumps({"is_chat": False}))
    heic = await extract(EvidenceKind.CHAT_SCREENSHOT, "p.heic", HEIC, "Sam", llm)
    not_chat = await extract(EvidenceKind.CHAT_SCREENSHOT, "p.png", PNG, "Sam", llm)
    assert (heic.error, heic.text, heic.messages) == ("unsupported", None, [])
    assert (not_chat.error, not_chat.text, not_chat.messages) == ("not a chat", None, [])
    assert len(_vision_calls(llm)) == 1  # the HEIC never reached the model


async def test_old_ingest_signature_still_works_for_text_kinds(tmp_path: Path) -> None:  # O18
    case = await ingest(
        _case(),
        EvidenceKind.CHAT_EXPORT,
        "chat.txt",
        IOS_LINE.encode(),
        "note",
        "Sam",
        uploads_dir=tmp_path,
    )
    assert case.messages[0].text == "Yes it is available."
    email = await ingest(case, EvidenceKind.EMAIL, None, b"Hello there", None, None)
    assert email.messages[-1].channel == "email"


async def test_screenshots_uploaded_as_chats_are_stored_and_deduped_as_screenshots(
    tmp_path: Path,
) -> None:
    """The web sends chat images as `chat_export` too: overlaps must still be deduped."""
    llm = _llm(chat=_chat(("left", "Deposit first please"), ("right", "Can I view?")))
    case = _case()
    for _ in range(2):
        case = await ingest(
            case, EvidenceKind.CHAT_EXPORT, "c.png", PNG, None, "Sam", uploads_dir=tmp_path, llm=llm
        )
    assert [e.kind for e in case.evidence] == [EvidenceKind.CHAT_SCREENSHOT] * 2
    assert [m.text for m in case.messages] == ["Deposit first please", "Can I view?"]
    assert case.evidence[1].extracted_text == case.evidence[0].extracted_text  # transcript kept


async def test_an_empty_file_is_an_error_for_every_kind() -> None:
    for kind in EvidenceKind:
        extracted = await extract(kind, "empty.png", b"", "Sam", FakeLLM())
        assert (extracted.text, extracted.messages, extracted.error) == (None, [], "empty")


async def test_a_corrupt_pdf_or_word_file_is_unreadable_not_a_crash() -> None:
    corrupt = (b"%PDF-1.7\n garbage", b"PK\x03\x04 not a real docx")
    for kind in (EvidenceKind.CONTRACT, EvidenceKind.LISTING, EvidenceKind.CHAT_EXPORT):
        extracted = await extract(kind, "x.pdf", corrupt[0], "Sam", FakeLLM())
        assert extracted.error == "unreadable"
        assert (extracted.text, extracted.messages) == (None, [])
    zip_error = await extract(EvidenceKind.CHAT_EXPORT, "x.zip", corrupt[1], "Sam", FakeLLM())
    assert zip_error.error == "zip"


async def test_a_word_file_sent_as_a_screenshot_is_read_not_decoded_as_bytes() -> None:
    extracted = await extract(EvidenceKind.CHAT_SCREENSHOT, "t.docx", _docx_bytes(), "Sam", None)
    assert extracted.error is None
    assert "£850 per month" in (extracted.text or "")
    assert "PK" not in (extracted.text or "")


async def test_a_screenshot_with_bank_details_is_stored_masked_without_the_raw_file(
    tmp_path: Path,
) -> None:
    bank = "Bank transfer, sort code 12-34-56, account 00001234."
    llm = _llm(chat=_chat(("left", bank), ("right", "Can I view first?")))
    case = await ingest(
        _case(),
        EvidenceKind.CHAT_SCREENSHOT,
        "chat.png",
        PNG,
        "sort code 12-34-56",
        "Sam",
        uploads_dir=tmp_path,
        llm=llm,
    )
    evidence = case.evidence[-1]
    stored = [evidence.extracted_text or "", evidence.note or "", *(m.text for m in case.messages)]
    for text in stored:
        assert "12-34-56" not in text
        assert "00001234" not in text
    assert "sort code **-**-56, account ****1234" in case.messages[0].text
    assert "sort code **-**-56, account ****1234" in (evidence.extracted_text or "")
    assert evidence.file_url is None  # text was read, so the image itself is not written


async def test_a_failed_read_keeps_the_raw_file_for_later(tmp_path: Path) -> None:
    llm = _llm(chat=json.dumps({"is_chat": False}))
    case = await ingest(
        _case(),
        EvidenceKind.CHAT_SCREENSHOT,
        "cat.png",
        PNG,
        None,
        "Sam",
        uploads_dir=tmp_path,
        llm=llm,
    )
    assert case.evidence[-1].extracted_text is None
    assert case.evidence[-1].file_url
