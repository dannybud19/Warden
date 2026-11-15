"""Upload to Evidence, extracted text and Messages.

Two steps, so the slow part (a vision call for images) can run without the case lock:
`extract` reads the upload (no case needed), `attach` adds the result to the case.
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.contracts import Case, Evidence, EvidenceKind, Message
from app.core.ids import new_id
from app.core.llm import LLMClient
from app.core.logging import get_logger
from app.intake import audio, docx, images, ocr, pdf, whatsapp, zip_export

UPLOADS_DIR = Path(__file__).resolve().parents[2] / ".uploads"  # backend/.uploads, gitignored

log = get_logger("intake")

Channel = Literal["whatsapp", "email", "sms", "call", "platform", "other"]
Sender = Literal["student", "agent", "unknown"]


@dataclass(frozen=True)
class Extracted:
    """What one upload yielded. `error` is an OCRError reason, shown to the student."""

    evidence_id: str
    text: str | None
    messages: list[Message] = field(default_factory=list)
    error: str | None = None


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").lstrip("﻿")


async def _document_text(data: bytes) -> str:
    """Text of a PDF, Word (.docx) or plain-text document (images are routed before this)."""
    if data.startswith(b"%PDF"):
        return pdf.extract_text(data)
    if docx.is_docx(data):
        return docx.extract_text(data)
    return _decode(data)


def _chat_text(
    data: bytes, evidence_id: str, student_name: str | None
) -> tuple[str, list[Message]]:
    """A chat export as text: a WhatsApp .zip or .txt, or any pasted text."""
    if zip_export.is_zip(data) and not docx.is_docx(data):
        text = zip_export.read_zip_export(data)
    else:
        text = _decode(data)
    messages = whatsapp.parse_export(text, evidence_id, student_name)
    if not messages and text.strip():
        # NOTE: not a WhatsApp export: keep the whole text as one message.
        messages = [_single_message(text, evidence_id, "other", "unknown")]
    return text, messages


def _safe_name(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name) or "upload"


async def _store(case_id: str, evidence_id: str, filename: str, data: bytes, base: Path) -> str:
    """Write the upload to disk; returns its path relative to backend/."""
    path = base / case_id / f"{evidence_id}_{_safe_name(filename)}"
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, data)
    return str(path.relative_to(base.parent))


def _single_message(text: str, evidence_id: str, channel: Channel, sender: Sender) -> Message:
    return Message(
        id=new_id("msg"), evidence_id=evidence_id, sender=sender, channel=channel, text=text.strip()
    )


async def _read_image(
    kind: EvidenceKind,
    data: bytes,
    evidence_id: str,
    student_name: str | None,
    llm: LLMClient,
) -> tuple[str, list[Message]]:
    """One vision call: a chat screenshot becomes messages, anything else plain text.

    Any unexpected error becomes `OCRError(LLM_ERROR)`, so an image upload never fails the request.
    """
    try:
        if kind in (EvidenceKind.CHAT_SCREENSHOT, EvidenceKind.CHAT_EXPORT):
            return await ocr.read_chat(data, llm, student_name, evidence_id)
        text = await ocr.read_document(data, llm)
    except (ocr.OCRError, images.ImageError, NotImplementedError):
        raise
    except Exception as exc:  # noqa: BLE001 - shown to the student as "try again"
        log.warning("image read failed for %s upload (%s)", kind.value, type(exc).__name__)
        raise ocr.OCRError(ocr.LLM_ERROR) from exc
    if kind == EvidenceKind.EMAIL:
        return text, [_single_message(text, evidence_id, "email", "agent")]
    return text, []


async def _extract_parts(
    kind: EvidenceKind,
    data: bytes,
    evidence_id: str,
    student_name: str | None,
    llm: LLMClient | None,
) -> tuple[str | None, list[Message]]:
    """Text and messages for one upload, routed by kind and by the bytes (never the filename)."""
    if kind in (EvidenceKind.CALL_RECORDING, EvidenceKind.VIDEO):
        return (await audio.transcribe(data) if kind == EvidenceKind.CALL_RECORDING else None), []
    if images.is_image(data):
        if llm is None:
            log.warning("image %s upload with no LLM: stored without text", kind.value)
            return None, []
        return await _read_image(kind, data, evidence_id, student_name, llm)
    match kind:
        case EvidenceKind.CHAT_EXPORT | EvidenceKind.CHAT_SCREENSHOT:
            # NOTE: text sent as a screenshot is read as a chat export (a wrong pick is common).
            return _chat_text(data, evidence_id, student_name)
        case EvidenceKind.EMAIL:
            text = _decode(data)
            return text, [_single_message(text, evidence_id, "email", "agent")]
        case _:  # contract, document, listing
            return await _document_text(data), []


async def extract(
    kind: EvidenceKind,
    filename: str | None,
    data: bytes,
    student_name: str | None,
    llm: LLMClient | None,
) -> Extracted:
    """Read one upload into text and Messages. Needs no case and holds no lock.

    Never raises for an unreadable image: the reason is returned in `error` instead.
    """
    evidence_id = new_id("ev")
    try:
        text, messages = await _extract_parts(kind, data, evidence_id, student_name, llm)
    except ocr.OCRError as exc:
        log.info("could not read %s upload: %s", kind.value, exc.reason)
        return Extracted(evidence_id, None, [], exc.reason)
    except images.ImageError as exc:
        return Extracted(evidence_id, None, [], exc.reason)
    except NotImplementedError as exc:
        log.warning("no extractor for %s yet (%s): stored without text", kind.value, exc)
        return Extracted(evidence_id, None, [])
    return Extracted(evidence_id, text, messages)


def _normalised(text: str) -> str:
    return " ".join(text.lower().split())


def _dedupe(case: Case, kind: EvidenceKind, messages: list[Message]) -> list[Message]:
    """Drop screenshot messages the case already has from an earlier screenshot (overlaps)."""
    if kind != EvidenceKind.CHAT_SCREENSHOT:
        return messages
    screenshots = {e.id for e in case.evidence if e.kind == EvidenceKind.CHAT_SCREENSHOT}
    seen = {(m.sender, _normalised(m.text)) for m in case.messages if m.evidence_id in screenshots}
    return [m for m in messages if (m.sender, _normalised(m.text)) not in seen]


async def attach(
    case: Case,
    kind: EvidenceKind,
    filename: str | None,
    data: bytes,
    note: str | None,
    extracted: Extracted,
    *,
    uploads_dir: Path | None = None,
) -> Case:
    """Store the file and return the Case with the new Evidence and its (deduped) Messages."""
    file_url = None
    if filename:
        file_url = await _store(
            case.case_id, extracted.evidence_id, filename, data, uploads_dir or UPLOADS_DIR
        )
    evidence = Evidence(
        id=extracted.evidence_id,
        kind=kind,
        uploaded_at=datetime.now(UTC),
        filename=filename,
        file_url=file_url,
        extracted_text=extracted.text,
        note=note,
    )
    messages = _dedupe(case, kind, extracted.messages)
    return case.model_copy(
        update={
            "evidence": [*case.evidence, evidence],
            "messages": [*case.messages, *messages],
        }
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
    llm: LLMClient | None = None,
) -> Case:
    """Create the Evidence, extract its text and Messages, and return the updated Case."""
    extracted = await extract(kind, filename, data, student_name, llm)
    return await attach(case, kind, filename, data, note, extracted, uploads_dir=uploads_dir)
