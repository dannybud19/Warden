"""Word (.docx) to text, with the standard library only (a .docx is a zip of XML)."""

import io
import zipfile
from xml.etree import ElementTree

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_BODY = "word/document.xml"
_MAX_XML_BYTES = 20 * 1024 * 1024  # NOTE: guards against zip bombs; real contracts are far smaller


def is_docx(data: bytes) -> bool:
    """True when the bytes are a zip that holds a Word document body."""
    if not data.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return _BODY in archive.namelist()
    except zipfile.BadZipFile:
        return False


def extract_text(data: bytes) -> str:
    """Paragraph text of the document body, one paragraph per line (tables included)."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.getinfo(_BODY).file_size > _MAX_XML_BYTES:
            raise ValueError("Word document is too large to read")
        root = ElementTree.fromstring(archive.read(_BODY))
    return "\n".join(_paragraph_text(p) for p in root.iter(f"{_W}p")).strip()


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t":
            parts.append(node.text or "")
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
    return "".join(parts)
