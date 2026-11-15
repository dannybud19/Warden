"""Contract and document uploads: plain text, Word (.docx) and photos."""

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from app.contracts import Case, EvidenceKind
from app.intake import docx
from app.intake.service import ingest

_DOC_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    "<w:p><w:r><w:t>Assured Shorthold Tenancy</w:t></w:r></w:p>"
    "<w:p><w:r><w:t>Rent: </w:t></w:r><w:r><w:t>£850 per month</w:t></w:r></w:p>"
    "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Deposit</w:t><w:tab/><w:t>£980</w:t></w:r></w:p>"
    "</w:tc></w:tr></w:tbl>"
    "</w:body></w:document>"
)


def _docx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", _DOC_XML)
    return buf.getvalue()


def _case() -> Case:
    return Case.model_validate({"case_id": "case_t", "created_at": datetime.now(UTC).isoformat()})


def test_docx_text_keeps_paragraphs_and_tables() -> None:
    data = _docx_bytes()
    assert docx.is_docx(data)
    assert docx.extract_text(data) == (
        "Assured Shorthold Tenancy\nRent: £850 per month\nDeposit\t£980"
    )


def test_plain_zip_is_not_docx() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("chat.txt", "hello")
    assert not docx.is_docx(buf.getvalue())
    assert not docx.is_docx(b"PK not really a zip")


async def test_contract_upload_reads_docx(tmp_path: Path) -> None:
    case = await ingest(
        _case(),
        EvidenceKind.CONTRACT,
        "tenancy.docx",
        _docx_bytes(),
        None,
        None,
        uploads_dir=tmp_path,
    )
    assert "£850 per month" in (case.evidence[0].extracted_text or "")


async def test_contract_upload_reads_txt(tmp_path: Path) -> None:
    case = await ingest(
        _case(),
        EvidenceKind.CONTRACT,
        "contract.txt",
        "Rent £850 pcm".encode(),
        None,
        None,
        uploads_dir=tmp_path,
    )
    assert case.evidence[0].extracted_text == "Rent £850 pcm"


async def test_contract_photo_is_not_decoded_as_text(tmp_path: Path) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    case = await ingest(
        _case(), EvidenceKind.CONTRACT, "contract.png", png, None, None, uploads_dir=tmp_path
    )
    # OCR is not built yet: the photo is stored, with no garbage text for the agents.
    assert case.evidence[0].extracted_text is None
    assert case.evidence[0].file_url
