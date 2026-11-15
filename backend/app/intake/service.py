"""Upload to Evidence, extracted text and Messages."""

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.contracts import Case, Evidence, EvidenceKind, Message
from app.core.ids import new_id
from app.core.logging import get_logger
from app.intake import audio, docx, ocr, pdf, whatsapp

UPLOADS_DIR = Path(__file__).resolve().parents[2] / ".uploads"  # backend/.uploads, gitignored

log = get_logger("intake")

Channel = Literal["whatsapp", "email", "sms", "call", "platform", "other"]
Sender = Literal["student", "agent", "unknown"]


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").lstrip("﻿")


_IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF", b"II*\x00", b"MM\x00*")


def _is_image(data: bytes) -> bool:
    """PNG, JPEG, GIF, WebP, TIFF or HEIC bytes (HEIC: 'ftyp' box at offset 4)."""
    return data.startswith(_IMAGE_MAGIC) or data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1")


async def _document_text(data: bytes) -> str:
    """Text of a PDF, Word (.docx), photo (OCR) or plain-text document."""
    if data.startswith(b"%PDF"):
        return pdf.extract_text(data)
    if docx.is_docx(data):
        return docx.extract_text(data)
    if _is_image(data):
        # NOTE: decoding image bytes as UTF-8 would hand agents garbage; OCR or no text.
        return await ocr.screenshot_to_text(data)
    return _decode(data)


def _safe_name(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name) or "upload"


async def _store(case_id: str, evidence_id: str, filename: str, data: bytes, base: Path) -> str:
    """Write the upload to disk; returns its path relative to backend/."""
    path = base / case_id / f"{evidence_id}_{_safe_name(filename)}"
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, data)
    return str(path.relative_to(base.parent))


async def _extract(
    kind: EvidenceKind, data: bytes, evidence_id: str, student_name: str | None
) -> tuple[str | None, list[Message]]:
    """Text and messages for one upload. Unsupported kinds give no text, with a warning."""
    try:
        match kind:
            case EvidenceKind.CHAT_EXPORT:
                text = _decode(data)
                messages = whatsapp.parse_export(text, evidence_id, student_name)
                if not messages and text.strip():
                    # NOTE: not a WhatsApp export: keep the whole text as one message.
                    messages = [_single_message(text, evidence_id, "other", "unknown")]
                return text, messages
            case EvidenceKind.EMAIL:
                text = _decode(data)
                return text, [_single_message(text, evidence_id, "email", "agent")]
            case EvidenceKind.CONTRACT | EvidenceKind.DOCUMENT:
                return await _document_text(data), []
            case EvidenceKind.LISTING:
                return _decode(data), []
            case EvidenceKind.CHAT_SCREENSHOT:
                return await ocr.screenshot_to_text(data), []
            case EvidenceKind.CALL_RECORDING:
                return await audio.transcribe(data), []
            case EvidenceKind.VIDEO:
                return None, []
    except NotImplementedError as exc:
        log.warning("no extractor for %s yet (%s): stored without text", kind.value, exc)
    return None, []


def _single_message(text: str, evidence_id: str, channel: Channel, sender: Sender) -> Message:
    return Message(
        id=new_id("msg"), evidence_id=evidence_id, sender=sender, channel=channel, text=text.strip()
    )


async def ingest(
    case: Case,
    kind: EvidenceKind,
    filename: str | None,
    data: bytes,
    note: str | None,
    student_name: str | None,
    *,
    uploads_dir: Path | None = None,
) -> Case:
    """Create the Evidence, extract its text and Messages, and return the updated Case."""
    evidence_id = new_id("ev")
    text, messages = await _extract(kind, data, evidence_id, student_name)
    file_url = None
    if filename:
        file_url = await _store(
            case.case_id, evidence_id, filename, data, uploads_dir or UPLOADS_DIR
        )
    evidence = Evidence(
        id=evidence_id,
        kind=kind,
        uploaded_at=datetime.now(UTC),
        filename=filename,
        file_url=file_url,
        extracted_text=text,
        note=note,
    )
    return case.model_copy(
        update={
            "evidence": [*case.evidence, evidence],
            "messages": [*case.messages, *messages],
        }
    )
