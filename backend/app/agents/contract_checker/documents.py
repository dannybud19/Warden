"""Local PDF/text extraction and exact citation validation."""

import hashlib
import io
import re

from pypdf import PdfReader

from app.agents.contract_checker.models import Citation, Document, Quote, Segment

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARACTERS = 100_000
MAX_PAGES = 50


class DocumentError(ValueError):
    """A document cannot be reviewed completely with the supported extractors."""


def extract_document(data: bytes, filename: str, document_id: str = "contract") -> Document:
    """Extract the whole text document, preserving page and observed clause references."""
    if not data or len(data) > MAX_BYTES:
        raise DocumentError("Supply a non-empty contract of at most 10 MiB.")
    pages: list[tuple[int | None, str]]
    if data.startswith(b"%PDF"):
        try:
            pdf = PdfReader(io.BytesIO(data))
            if pdf.is_encrypted:
                raise DocumentError("Supply an unencrypted text-based PDF.")
            if len(pdf.pages) > MAX_PAGES:
                raise DocumentError("The first version supports at most 50 PDF pages.")
            pages = [(i + 1, page.extract_text() or "") for i, page in enumerate(pdf.pages)]
        except DocumentError:
            raise
        except Exception as exc:
            raise DocumentError(
                "The PDF could not be read; supply a valid text-based PDF."
            ) from exc
        if any(not text.strip() for _, text in pages):
            raise DocumentError(
                "A PDF page has no extractable text. Supply a complete text-based copy; "
                "scanned or blank pages cannot be silently skipped."
            )
    else:
        if filename.lower().endswith(".pdf") or data.startswith((b"PK", b"\x89PNG", b"\xff\xd8")):
            raise DocumentError("Only text-based PDFs and UTF-8 plain text are supported.")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentError("Plain text must be UTF-8 encoded.") from exc
        if "\x00" in text:
            raise DocumentError("Binary input is not a plain-text contract.")
        pages = [(None, text)]
    if sum(len(text) for _, text in pages) > MAX_CHARACTERS:
        raise DocumentError("Contract exceeds 100,000 characters; no text was silently truncated.")
    segments: list[Segment] = []
    for page, text in pages:
        current_clause = ""
        for line in text.splitlines():
            if not line.strip():
                continue
            match = re.match(r"^\s*(?:clause\s+)?(\d+(?:\.\d+)*)(?:[.)\s])", line, re.I)
            if match:
                current_clause = match.group(1)
            ordinal = len(segments) + 1
            segments.append(
                Segment(
                    id=f"s{ordinal}",
                    text=line,
                    page=page,
                    clause_id=current_clause or f"Paragraph {ordinal}",
                )
            )
    if not segments:
        raise DocumentError("No contract text was found.")
    return Document(
        id=document_id,
        filename=filename,
        sha256=hashlib.sha256(data).hexdigest(),
        segments=segments,
    )


def cite(document: Document, reference: Quote) -> Citation | None:
    """Return observed metadata only when an exact quote occurs in its claimed segment."""
    segment = next((s for s in document.segments if s.id == reference.segment_id), None)
    if segment is None or not reference.quote.strip() or reference.quote not in segment.text:
        return None
    return Citation(
        segment_id=reference.segment_id,
        quote=reference.quote,
        document_id=document.id,
        clause_id=segment.clause_id,
        page=segment.page,
    )


def cite_all(document: Document, references: list[Quote]) -> list[Citation] | None:
    """Reject the entire evidence set when even one supporting quote is fabricated."""
    citations = [cite(document, ref) for ref in references]
    if not citations or any(ref is None for ref in citations):
        return None
    return [ref for ref in citations if ref is not None]
