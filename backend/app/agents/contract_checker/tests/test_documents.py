import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.agents.contract_checker.documents import DocumentError, cite, extract_document
from app.agents.contract_checker.models import Citation, Quote


def pdf_bytes(text: str | None) -> bytes:
    """Create a real minimal PDF so extraction is exercised without external tools."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    if text is not None:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 40 700 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_text_extraction_preserves_observed_page_and_clause() -> None:
    document = extract_document(pdf_bytes("2. Rent: GBP 1300 per month"), "agreement.pdf")
    ref = cite(document, Quote(segment_id="s1", quote="Rent: GBP 1300"))
    assert ref is not None and ref.page == 1 and ref.clause_id == "2"


def test_wrong_segment_or_fabricated_quote_is_rejected() -> None:
    document = extract_document(b"1. Rent: GBP 1300\n2. Deposit: GBP 1500", "contract.txt")
    assert cite(document, Quote(segment_id="s2", quote="Rent: GBP 1300")) is None
    assert cite(document, Quote(segment_id="s1", quote="Rent: GBP 130")) is not None
    assert cite(document, Quote(segment_id="s1", quote="Rent: GBP 900")) is None


def test_revalidating_a_citation_uses_observed_metadata() -> None:
    document = extract_document(b"2. Rent: GBP 1300", "contract.txt", "current")
    supplied = Citation(
        segment_id="s1", quote="Rent: GBP 1300", document_id="old", clause_id="99", page=12
    )
    checked = cite(document, supplied)
    assert checked is not None
    assert (checked.document_id, checked.clause_id, checked.page) == ("current", "2", None)


@pytest.mark.parametrize(
    "data,name",
    [
        (b"", "empty.txt"),
        (b"\xff\xfe", "bad.txt"),
        (b"PK\x03\x04data", "document.docx"),
        (b"not a PDF", "contract.pdf"),
        (b"a\x00b", "binary.txt"),
    ],
)
def test_bad_inputs_are_explicitly_rejected(data: bytes, name: str) -> None:
    with pytest.raises(DocumentError):
        extract_document(data, name)


def test_blank_or_scanned_page_is_not_silently_ignored() -> None:
    with pytest.raises(DocumentError, match="no extractable text"):
        extract_document(pdf_bytes(None), "scan.pdf")


def test_plain_text_does_not_invent_a_page_or_numbered_clause() -> None:
    document = extract_document("Rent: £850 per calendar month".encode(), "contract.txt")
    assert document.segments[0].page is None
    assert document.segments[0].clause_id == "Paragraph 1"
