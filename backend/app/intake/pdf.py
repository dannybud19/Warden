"""PDF to text."""

import io

from pypdf import PdfReader


def extract_text(data: bytes) -> str:
    """Text of all pages joined with blank lines."""
    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
