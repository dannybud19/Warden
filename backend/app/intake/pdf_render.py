"""Bounded PDF parsing/rendering worker. Run in a child process: PDFium is not thread-safe."""

import base64
import io
import json
import math
import sys
from contextlib import ExitStack

import pypdfium2 as pdfium
from pypdf import PdfReader

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20
MAX_SCANNED_PAGES = 5
MAX_TEXT = 200_000


class PDFLimitError(ValueError):
    """The file exceeds the email-PDF processing limits."""


def read_pages(data: bytes) -> list[dict[str, str]]:
    """Extract selectable text and render only pages that need OCR, preserving page order."""
    if len(data) > MAX_BYTES:
        raise PDFLimitError
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted or len(reader.pages) > MAX_PAGES:
        raise PDFLimitError
    result: list[dict[str, str]] = []
    scanned = 0
    total_text = 0
    with ExitStack() as resources:
        document = None
        for index, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            total_text += len(text)
            if total_text > MAX_TEXT:
                raise PDFLimitError
            if text:
                result.append({"text": text})
                continue
            if document is None:
                document = pdfium.PdfDocument(data)
                resources.callback(document.close)
            with ExitStack() as page_resources:
                rendered_page = document[index]
                page_resources.callback(rendered_page.close)
                width, height = rendered_page.get_size()
                if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                    raise ValueError("invalid page dimensions")
                bitmap = rendered_page.render(scale=min(2.0, 1800 / max(width, height)))
                page_resources.callback(bitmap.close)
                original = bitmap.to_pil()
                page_resources.callback(original.close)
                image = original.convert("RGB")
                page_resources.callback(image.close)
                if all(extrema == (255, 255) for extrema in image.getextrema()):
                    result.append({"text": ""})  # a blank separator page needs no paid OCR call
                    continue
                scanned += 1
                if scanned > MAX_SCANNED_PAGES:
                    raise PDFLimitError
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=90)
                result.append({"image": base64.b64encode(output.getvalue()).decode("ascii")})
    return result


def main() -> None:
    """Read one PDF on stdin and return JSON only; never log source text or file contents."""
    try:
        pages = read_pages(sys.stdin.buffer.read(MAX_BYTES + 1))
        result = {"pages": pages}
    except PDFLimitError:
        result = {"error": "pdf_limit"}
    except Exception:  # noqa: BLE001 - native/parser failures are reported without document data
        result = {"error": "pdf_unreadable"}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=True).encode("ascii"))


if __name__ == "__main__":
    main()
