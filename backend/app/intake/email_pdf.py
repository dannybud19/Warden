"""Email PDFs: selectable text first, bounded vision OCR for pages without text."""

import asyncio
import base64
import json
import os
import subprocess
import sys
from contextlib import suppress

from app.core.llm import LLMClient
from app.intake import ocr, pdf
from app.intake.pdf_render import MAX_BYTES

LIMIT = "pdf_limit"
OCR_FAILED = "pdf_ocr_failed"
RENDER_TIMEOUT_S = 15.0
OCR_TIMEOUT_S = 100.0


async def _pages(data: bytes) -> list[dict[str, str]]:
    if len(data) > MAX_BYTES:
        raise ocr.OCRError(LIMIT)
    # A process isolates native PDF parsing, permits a hard timeout, and avoids PDFium's
    # thread-safety restriction when students upload several PDFs at the same time.
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.intake.pdf_render",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(data), RENDER_TIMEOUT_S)
        if process.returncode != 0:
            raise ocr.OCRError(pdf.UNREADABLE)
        result = json.loads(output)
        if result.get("error"):
            raise ocr.OCRError(result["error"])
        return result["pages"]
    except (TimeoutError, ValueError, KeyError) as exc:
        raise ocr.OCRError(pdf.UNREADABLE) from exc
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()


async def read(data: bytes, llm: LLMClient | None) -> str:
    """Read every page or return a visible error; never silently analyse a partial email PDF."""
    pages = await _pages(data)
    texts: list[str] = []
    try:
        async with asyncio.timeout(OCR_TIMEOUT_S):
            for page in pages:
                if "text" in page:
                    texts.append(page["text"])
                elif llm is not None:
                    texts.append(await ocr.read_document(base64.b64decode(page["image"]), llm))
                else:
                    raise ocr.OCRError(OCR_FAILED)
    except (ocr.OCRError, TimeoutError) as exc:
        raise ocr.OCRError(OCR_FAILED) from exc
    text = "\n\n".join(texts).strip()
    if not text:
        raise ocr.OCRError(pdf.UNREADABLE)
    return text
