"""Email PDF uploads must become readable messages rather than raw PDF source."""

import asyncio
import io
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter

from app.agents.contract_checker.tests.test_documents import pdf_bytes
from app.contracts import EvidenceKind, StudentContext
from app.core.agent import BaseAgent
from app.core.llm import FakeLLM
from app.intake import email_pdf, ocr
from app.intake import service as intake
from app.orchestrator.service import CaseService, Upload
from tests.conftest import EmptyAgent

MakeService = Callable[[list[BaseAgent] | None], CaseService]


def scanned_pdf() -> bytes:
    """A real image-only PDF, rendered by the production PDFium worker in offline tests."""
    with Image.new("RGB", (900, 600), "white") as image:
        ImageDraw.Draw(image).text(
            (40, 70), "Viewing confirmed Tuesday. Account 00001234.", fill="black", font_size=24
        )
        output = io.BytesIO()
        image.save(output, format="PDF")
        return output.getvalue()


def combine(*documents: bytes) -> bytes:
    writer = PdfWriter()
    for data in documents:
        writer.append(io.BytesIO(data))
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class InspectingVision(FakeLLM):
    async def describe_image(self, image: bytes, prompt: str) -> str:
        with Image.open(io.BytesIO(image)) as rendered:
            assert rendered.format == "JPEG"
            assert max(rendered.size) <= 1800
        return await super().describe_image(image, prompt)


async def test_scanned_and_mixed_email_pages_are_ocrd_in_order_and_masked() -> None:
    llm = InspectingVision(
        default=json.dumps(
            {
                "is_document": True,
                "text": "Viewing confirmed Tuesday. Account 00001234.",
                "unreadable": False,
            }
        )
    )
    data = combine(pdf_bytes("First email page."), scanned_pdf(), pdf_bytes("Last email page."))
    result = await intake.extract(EvidenceKind.EMAIL, "mixed.pdf", data, "Sam", llm)
    assert result.error is None
    assert result.text and result.text.startswith("First email page.")
    assert result.text.endswith("Last email page.")
    assert "Viewing confirmed Tuesday." in result.text and "00001234" not in result.text
    assert len(llm.calls) == 1  # text pages are free; only the scanned page uses vision
    assert result.messages[0].text == result.text


async def test_unreadable_scanned_page_does_not_silently_drop_part_of_email() -> None:
    llm = FakeLLM(default='{"is_document": true, "text": "", "unreadable": true}')
    data = combine(pdf_bytes("Readable first page."), scanned_pdf())
    result = await intake.extract(EvidenceKind.EMAIL, "partial.pdf", data, "Sam", llm)
    assert result.error == email_pdf.OCR_FAILED
    assert result.text is None and not result.messages


async def test_scanned_pdf_requires_a_vision_reader() -> None:
    result = await intake.extract(EvidenceKind.EMAIL, "scan.pdf", scanned_pdf(), None, None)
    assert result.error == email_pdf.OCR_FAILED


async def test_blank_separator_pages_do_not_need_ocr() -> None:
    llm = FakeLLM()
    data = combine(pdf_bytes("First page."), pdf_bytes(None), pdf_bytes("Second page."))
    result = await intake.extract(EvidenceKind.EMAIL, "email.pdf", data, None, llm)
    assert result.error is None and result.text and "Second page." in result.text
    assert not llm.calls


@pytest.mark.parametrize(
    "data",
    [
        b"%PDF" + b"x" * email_pdf.MAX_BYTES,
        combine(*[pdf_bytes("page")] * 21),
        combine(*[scanned_pdf()] * 6),
    ],
)
async def test_email_pdf_limits_are_visible_and_make_no_llm_calls(data: bytes) -> None:
    llm = FakeLLM()
    result = await intake.extract(EvidenceKind.EMAIL, "large.pdf", data, None, llm)
    assert result.error == email_pdf.LIMIT
    assert not result.messages and not llm.calls


async def test_scan_timeout_is_a_retryable_read_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class SlowVision(FakeLLM):
        async def describe_image(self, image: bytes, prompt: str) -> str:
            await asyncio.sleep(1)
            return "{}"

    monkeypatch.setattr(ocr, "VISION_TIMEOUT_S", 0.01)
    result = await intake.extract(EvidenceKind.EMAIL, "scan.pdf", scanned_pdf(), None, SlowVision())
    assert result.error == email_pdf.OCR_FAILED


async def test_email_pdf_extracts_every_page_and_masks_bank_details() -> None:
    writer = PdfWriter()
    for text in (
        "Your viewing is confirmed for Tuesday.",
        "Bank transfer, sort code 12-34-56, account 00001234.",
    ):
        writer.add_page(PdfReader(io.BytesIO(pdf_bytes(text))).pages[0])
    output = io.BytesIO()
    writer.write(output)
    llm = FakeLLM()
    result = await intake.extract(EvidenceKind.EMAIL, "viewing.pdf", output.getvalue(), "Sam", llm)

    assert result.error is None
    assert result.text and result.text.startswith("Your viewing is confirmed for Tuesday.")
    assert "Bank transfer" in result.text
    assert "00001234" not in result.text and "12-34-56" not in result.text
    assert "%PDF" not in result.text
    assert len(result.messages) == 1
    message = result.messages[0]
    assert (message.channel, message.sender) == ("email", "agent")
    assert message.evidence_id == result.evidence_id
    assert message.text == result.text.strip()
    assert llm.calls == []


@pytest.mark.parametrize("existing", [False, True])
async def test_email_pdf_is_read_on_new_and_existing_cases(
    make_service: MakeService,
    existing: bool,
) -> None:
    service: CaseService = make_service([EmptyAgent()])
    case = await service.open_case(StudentContext())
    if existing:
        await service.add_evidence(case.case_id, Upload(EvidenceKind.DOCUMENT, b"Earlier evidence"))
        await service.wait_idle()

    stored = await service.add_evidence(
        case.case_id,
        Upload(EvidenceKind.EMAIL, pdf_bytes("A viewing is confirmed for Tuesday."), "email.pdf"),
    )
    await service.wait_idle()
    assert len(stored.evidence) == (2 if existing else 1)
    assert stored.evidence[-1].extracted_text == "A viewing is confirmed for Tuesday."
    assert stored.messages[-1].text == "A viewing is confirmed for Tuesday."
    assert stored.evidence[-1].file_url is None


@pytest.mark.parametrize("data", [pdf_bytes(None), b"%PDF-1.7\nnot a valid PDF"])
async def test_unreadable_email_pdf_gets_a_persistent_explanation_without_analysis(
    make_service: MakeService,
    data: bytes,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intake, "UPLOADS_DIR", tmp_path / ".uploads")
    service: CaseService = make_service([EmptyAgent()])
    case = await service.open_case(StudentContext())
    stored = await service.add_evidence(case.case_id, Upload(EvidenceKind.EMAIL, data, "email.pdf"))

    assert stored.evidence[-1].extracted_text is None
    assert stored.messages == []
    assert "PDF" in stored.chat[-1].text
    assert "screenshot" in stored.chat[-1].text
    assert not service._tasks
    reloaded = await service.get_case(case.case_id)
    assert reloaded.chat[-1].text == stored.chat[-1].text
